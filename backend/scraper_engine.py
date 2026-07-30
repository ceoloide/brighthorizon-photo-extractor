# SPDX-License-Identifier: MIT
# Headless Scraper Engine for Bright Horizons Photo Extractor
import json
import os
import re
import sys
import time
import requests
import struct
import threading
import zlib
from datetime import datetime, timedelta
from typing import Dict, Any, List, Callable, Optional, Tuple
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright, BrowserContext, Page
from backend.database import TenantStorage

FLARESOLVERR_URL = os.environ.get("FLARESOLVERR_URL", "http://192.168.1.176:8191/v1")

def ensure_xvfb_display(width=1280, height=720):
    """Ensures Xvfb virtual display is active for headful Chromium execution."""
    os.system("pkill -f Xvfb 2>/dev/null")
    time.sleep(0.3)
    os.system(f"Xvfb :99 -screen 0 {width}x{height}x24 > /dev/null 2>&1 &")
    os.environ["DISPLAY"] = ":99"
    time.sleep(0.5)

def capture_compressed_b64_frame(page: Page, width=1280, height=720) -> Optional[str]:
    """Captures a lightweight JPEG screenshot (quality=45) encoded in Base64 for live preview streaming."""
    try:
        img_bytes = page.screenshot(type="jpeg", quality=45, clip={"x": 0, "y": 0, "width": width, "height": height})
        import base64
        return f"data:image/jpeg;base64,{base64.b64encode(img_bytes).decode('utf-8')}"
    except Exception:
        try:
            img_bytes = page.screenshot(type="jpeg", quality=45)
            import base64
            return f"data:image/jpeg;base64,{base64.b64encode(img_bytes).decode('utf-8')}"
        except Exception:
            return None

def clean_user_data_locks(user_data_dir: str):
    """Safely removes stale Chromium Singleton lock files to prevent browser launch crashes."""
    if not os.path.exists(user_data_dir):
        return
    for root, dirs, files in os.walk(user_data_dir):
        for fname in files:
            if "Singleton" in fname or fname == "RunningChromeVersion":
                try:
                    os.remove(os.path.join(root, fname))
                except Exception:
                    pass

class ScraperJob:
    def __init__(self, tenant_storage: TenantStorage, password: str, options: Dict[str, Any], log_callback: Optional[Callable[[str], None]] = None):
        self.tenant_storage = tenant_storage
        self.email = tenant_storage.email
        self.password = password
        self.options = options
        self.sync_mode = options.get("sync_mode", "incremental") # "incremental", "full", "custom"
        self.start_date = options.get("start_date") # "YYYY-MM-DD" string
        self.layout_mode = "flat" # Hardcode to flat mode
        self.target_child = options.get("child", "all")
        self.log_callback = log_callback or (lambda msg: print(f"[{self.email}] {msg}"))
        self._active_page: Optional[Page] = None
        self._cancelled = False
        
        self.status = {
            "state": "idle",
            "current_step": "Initializing",
            "files_downloaded": 0,
            "error": None,
            "logs": []
        }
        self._mfa_code: Optional[str] = None
        self._mfa_event = threading.Event()
        self._active_page: Optional[Page] = None
        self._manual_step_mode: bool = options.get("manual_step_mode", False)
        self._step_event = threading.Event()

    def submit_mfa_code(self, code: str) -> bool:
        """Thread-safe method to submit volatile MFA verification code from UI."""
        code_clean = code.strip()
        if not code_clean.isdigit() or len(code_clean) != 6:
            return False
        self._mfa_code = code_clean
        self._mfa_event.set()
        return True

    def advance_step(self) -> bool:
        """Thread-safe method to advance to the next substep when manual stepping is enabled."""
        self._step_event.set()
        return True

    def human_type(self, page: Page, locator, text: str):
        """Types text with realistic human keystroke intervals (65-145ms per key with natural pauses)."""
        import random
        locator.click(force=True)
        page.wait_for_timeout(random.randint(150, 300))
        locator.fill("")
        page.wait_for_timeout(random.randint(100, 200))
        for char in text:
            locator.type(char, delay=random.randint(65, 145))
            if random.random() < 0.15:
                page.wait_for_timeout(random.randint(100, 220))

    def click_preview(self, x_percent: float, y_percent: float):
        """Replicates a user tap or click from the 360x640 mobile preview onto the XVFB headful browser page."""
        if hasattr(self, "_active_page") and self._active_page and not self._active_page.is_closed():
            try:
                x_px = int(x_percent * 360)
                y_px = int(y_percent * 640)
                self.log(f"Replicating preview tap at ({x_px}px, {y_px}px) on 360x640 mobile display...")
                self._active_page.mouse.click(x_px, y_px)
            except Exception as e:
                self.log(f"Preview tap replication error: {e}")

    def log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self.status["logs"].append(entry)
        if len(self.status["logs"]) > 200:
            self.status["logs"].pop(0)
        self.log_callback(entry)

    def solve_cloudflare_flaresolverr(self, target_url: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Queries FlareSolverr API to resolve Cloudflare turnstile/bot challenges and return session cookies & matching User-Agent."""
        try:
            self.log(f"Querying FlareSolverr endpoint ({FLARESOLVERR_URL}) to bypass Cloudflare protection...")
            payload = {
                "cmd": "request.get",
                "url": target_url,
                "maxTimeout": 60000
            }
            resp = requests.post(FLARESOLVERR_URL, json=payload, timeout=70)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok":
                    solution = data.get("solution", {})
                    cookies = solution.get("cookies", [])
                    user_agent = solution.get("userAgent")
                    self.log(f"FlareSolverr successfully resolved challenge ({len(cookies)} clearance cookies received).")
                    return cookies, user_agent
        except Exception as e:
            self.log(f"FlareSolverr request failed (will fall back to native Playwright stealth): {e}")
        return [], None

    def run(self):
        self.status["state"] = "running"
        self.status["current_step"] = "Starting headless browser"
        self.log("Starting headless extraction job...")
        
        user_data_dir = self.tenant_storage.user_data_dir
        
        try:
            # Query FlareSolverr for initial clearance cookies & User-Agent
            clearance_cookies, solver_ua = self.solve_cloudflare_flaresolverr("https://familyinfocenter.brighthorizons.com/home")
            
            ensure_xvfb_display()
            with sync_playwright() as p:
                args = [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--window-size=360,640",
                    "--use-mobile-user-agent"
                ]
                
                context_kwargs = {
                    "args": args,
                    "ignore_default_args": ["--enable-automation"],
                    "headless": False,
                    "viewport": {"width": 360, "height": 640},
                    "is_mobile": True,
                    "has_touch": True,
                    "device_scale_factor": 2,
                    "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
                }
                
                # Attempt using real Chrome browser channel if available
                try:
                    context: BrowserContext = p.chromium.launch_persistent_context(
                        user_data_dir,
                        channel="chrome",
                        **context_kwargs
                    )
                except Exception:
                    context: BrowserContext = p.chromium.launch_persistent_context(
                        user_data_dir,
                        **context_kwargs
                    )
                
                state_file = os.path.join(user_data_dir, "storage_state.json")
                if os.path.exists(state_file):
                    try:
                        with open(state_file, "r") as sf:
                            state_data = json.load(sf)
                        if state_data.get("cookies"):
                            context.add_cookies(state_data["cookies"])
                            self.log(f"Loaded {len(state_data['cookies'])} cookies from storage_state.json into Playwright context.")
                    except Exception as e:
                        self.log(f"Notice loading storage_state.json: {e}")

                if clearance_cookies:
                    formatted_cookies = []
                    for c in clearance_cookies:
                        formatted_cookies.append({
                            "name": c["name"],
                            "value": c["value"],
                            "domain": c["domain"],
                            "path": c.get("path", "/"),
                            "secure": c.get("secure", False)
                        })
                    context.add_cookies(formatted_cookies)
                
                page: Page = context.new_page()
                
                # Step 1: Check login & authenticate
                self.status["current_step"] = "Authenticating with Bright Horizons"
                self.perform_login(page)
                
                # Step 2: Auto-discover children following Angular CDK rules (.agents/AGENTS.md)
                self.status["current_step"] = "Discovering enrolled children"
                self.log("Discovering children profiles...")
                children = self.discover_children(page, context)
                
                if not children:
                    self.log("No children auto-discovered via portal. Checking existing config...")
                    config = self.tenant_storage.load_config()
                    children = config.get("children", [])
                else:
                    config = self.tenant_storage.load_config()
                    config["children"] = children
                    self.tenant_storage.save_config(config)
                    
                if not children:
                    raise Exception("No active children profiles found for this account.")
                    
                self.log(f"Discovered {len(children)} children: {[c['name'] for c in children]}")
                
                # Step 3: Extract photos/videos for children
                self.status["current_step"] = "Extracting photos & videos"
                for child in children:
                    if self.target_child != "all" and child["name"].lower() != self.target_child.lower():
                        continue
                    self.extract_child_feed(page, context, child)
                    
                self.status["state"] = "completed"
                self.status["current_step"] = "Extraction finished successfully"
                self.log("All extraction tasks completed successfully!")
                
        except Exception as e:
            self.status["state"] = "failed"
            self.status["error"] = str(e)
            self.log(f"Extraction failed: {e}")

    def detect_page_state(self, page: Page, max_wait_sec: int = 35) -> str:
        """
        Polls DOM for up to max_wait_sec to detect true page state under slow network/JS redirect conditions.
        Returns: 'authenticated', 'auth0_username', 'auth0_password', 'landing_login_btn', or 'unknown'.
        """
        start_time = time.time()
        while time.time() - start_time < max_wait_sec:
            url_lower = page.url.lower()

            # 1. On Auth0 / SSO domain, check login inputs directly (never authenticated)
            if "auth0.com" in url_lower or "bhloginsso" in url_lower or "login.brighthorizons" in url_lower:
                mfa_inp = page.locator("input[name='code'], input[id='code']")
                if "mfa" in url_lower or (mfa_inp.count() > 0 and mfa_inp.first.is_visible()):
                    return "auth0_mfa"

                pwd_inp = page.locator("input[name='password']:not(.hide), input[id='password']")
                if pwd_inp.count() > 0 and pwd_inp.first.is_visible():
                    return "auth0_password"

                username_inp = page.locator("input[name='username'], input[id='username'], input[type='email']")
                if username_inp.count() > 0 and username_inp.first.is_visible():
                    return "auth0_username"

                page.wait_for_timeout(1000)
                continue

            # 2. Check if authenticated home loaded (Actions buttons on child cards)
            if page.locator("span:has-text('Actions')").count() > 0:
                return "authenticated"

            # 3. Check for portal Log In button on landing page (e.g. /okta/login)
            login_btn = page.locator("button:has-text('Log In'), a:has-text('Log In'), button:has-text('Sign In'), a:has-text('Sign In')")
            if login_btn.count() > 0 and login_btn.first.is_visible():
                return "landing_login_btn"

            page.wait_for_timeout(1000)

        return "unknown"

    def wait_for_manual_step(self, step_name: str, step_idx: int, update_cb: Optional[Callable[[str, int], None]] = None):
        """Pauses execution until user clicks Next in UI (10 min timeout)."""
        if update_cb:
            update_cb(step_name, step_idx)
        self._step_event.clear()
        self.log(f"Paused at step: '{step_name}'. Waiting for user to click Next in UI...")
        self._step_event.wait(timeout=600)

    def perform_login(self, page: Page, update_progress_cb: Optional[Callable[[str, int], None]] = None):
        """Ultra-robust login handler following the exact Bright Horizons & Auth0 SSO authentication sequence."""
        self._active_page = page
        self.log("Navigating to familyinfocenter.brighthorizons.com/okta/login...")
        page.goto("https://familyinfocenter.brighthorizons.com/okta/login", wait_until="domcontentloaded")
        page.wait_for_timeout(2500)
        
        state = self.detect_page_state(page, max_wait_sec=35)
        self.log(f"Detected page state: '{state}' (URL: {page.url})")
        
        if state == "authenticated":
            self.log("Already authenticated via active browser session!")
            return

        # Step 1: Wait for and click Landing Page "Log In" button
        if state == "landing_login_btn":
            self.log("Clicking portal Log In button...")
            if update_progress_cb: update_progress_cb("Clicking portal Log In button...", 2)
            btn = page.locator("button:has-text('Log In'), a:has-text('Log In'), button:has-text('Sign In'), a:has-text('Sign In')").first
            btn.click()
            page.wait_for_load_state("domcontentloaded")
            state = self.detect_page_state(page, max_wait_sec=35)
            self.log(f"Post-click page state: '{state}' (URL: {page.url})")

        if state in ["auth0_username", "auth0_password"]:
            self.log("Auth0 SSO login form loaded.")
            
            if state == "auth0_username":
                username_inp = page.locator("input[name='username'], input[id='username'], input[type='email']").first
                username_inp.wait_for(state="visible", timeout=25000)
                
                # Step 2: Wait for Cloudflare Turnstile verification ("Success!" / "Verify you are human")
                self.log("Waiting for Cloudflare Turnstile verification...")
                if update_progress_cb: update_progress_cb("Waiting for security check...", 2)
                
                turnstile_verified = False
                for sec in range(25):
                    body_text = page.locator("body").inner_text()
                    body_lower = body_text.lower()
                    
                    if "success!" in body_lower or "success" in body_lower:
                        self.log(f"Cloudflare Turnstile auto-verified (Success!) after {sec+1} seconds.")
                        turnstile_verified = True
                        break
                    elif "verify you are human" in body_lower or "verify you are a human" in body_lower:
                        self.log(f"Turnstile requires click (sec {sec+1}). Solved via frame click...")
                        turnstile_iframe = page.locator("iframe[src*='challenges.cloudflare.com']").first
                        if turnstile_iframe.count() > 0 and turnstile_iframe.is_visible():
                            box = turnstile_iframe.bounding_box()
                            if box:
                                page.mouse.click(box['x'] + 30, box['y'] + (box['height'] / 2))
                                page.wait_for_timeout(3000)
                    elif "verifying" in body_lower:
                        pass
                        
                    page.wait_for_timeout(1000)

                # Optional manual step pause before entering email if manual_step_mode is enabled
                if self._manual_step_mode:
                    self.wait_for_manual_step("Turnstile check complete. Click Next to type email.", 2, update_progress_cb)

                # Step 3: Type email address with realistic human keystroke timing and press Continue
                self.log("Typing email address into SSO username input...")
                if update_progress_cb: update_progress_cb("Typing email address...", 2)
                
                self.human_type(page, username_inp, self.email)
                page.wait_for_timeout(1000)
                
                cont_btn = page.locator("button._button-login-id, button[type='submit']:not(.ulp-hidden-form-submit-button), button[name='action'], button:has-text('Continue')").first
                self.log("Clicking Continue button...")
                if cont_btn.count() > 0 and cont_btn.is_visible():
                    cont_btn.click(force=True)
                else:
                    username_inp.press("Enter")
                    
                page.wait_for_timeout(3500)

            # Step 4: Type password with realistic human keystroke timing and press Continue
            pwd_inp = page.locator("input[name='password']:not(.hide), input[id='password']").first
            pwd_inp.wait_for(state="visible", timeout=25000)
            
            if self._manual_step_mode:
                self.wait_for_manual_step("Password field visible. Click Next to submit password.", 2, update_progress_cb)

            self.log("Filling password...")
            if update_progress_cb: update_progress_cb("Submitting password...", 2)
            self.human_type(page, pwd_inp, self.password)
            page.wait_for_timeout(500)
            
            login_btn = page.locator("button[type='submit']:not(.ulp-hidden-form-submit-button), button[name='action'], button:has-text('Log In'), button:has-text('Sign In'), button:has-text('Continue')").first
            if login_btn.count() > 0 and login_btn.is_visible():
                login_btn.click(force=True)
            else:
                pwd_inp.press("Enter")
                
            self.log("Waiting for post-login redirection or MFA challenge...")
            page.wait_for_timeout(3500)
            
            # Step 5: Email Verification Code (MFA) & "Remember this device for 30 days"
            state = self.detect_page_state(page, max_wait_sec=10)
            mfa_inp_check = page.locator("input[name='code'], input[id='code']")
            body_text = page.locator("body").inner_text()
            if "Verify your identity" in body_text or state == "auth0_mfa" or "mfa" in page.url.lower() or (mfa_inp_check.count() > 0 and mfa_inp_check.first.is_visible()):
                self.log("Auth0 MFA Email Verification required!")
                
                # Automatically select "Remember this device for 30 days" checkbox
                remember_chk = page.locator("input[type='checkbox'], label:has-text('Remember')").first
                if remember_chk.count() > 0 and remember_chk.is_visible():
                    try:
                        self.log("Selecting 'Remember this device for 30 days'...")
                        remember_chk.click(force=True)
                    except Exception as e:
                        self.log(f"Remember checkbox notice: {e}")

                self.status["state"] = "mfa_required"
                self.status["current_step"] = "Waiting for Email Verification Code"
                if update_progress_cb: update_progress_cb("Email verification code required", 2)
                
                self._mfa_event.clear()
                got_code = self._mfa_event.wait(timeout=120)
                if not got_code or not self._mfa_code:
                    raise Exception("MFA verification timed out after 120 seconds.")
                
                code_to_submit = self._mfa_code
                self._mfa_code = None # Overwrite and clear immediately from volatile memory!
                
                self.log("Submitting MFA code to Auth0 with realistic typing...")
                if update_progress_cb: update_progress_cb("Submitting verification code...", 2)
                mfa_inp = page.locator("input[name='code'], input[id='code'], input[type='text']").first
                mfa_inp.wait_for(state="visible", timeout=10000)
                self.human_type(page, mfa_inp, code_to_submit)
                page.wait_for_timeout(500)
                
                submit_mfa_btn = page.locator("button[type='submit']:not(.ulp-hidden-form-submit-button), button[name='action'], button:has-text('Continue'), button:has-text('Verify')").first
                if submit_mfa_btn.count() > 0 and submit_mfa_btn.is_visible():
                    submit_mfa_btn.click(force=True)
                else:
                    mfa_inp.press("Enter")
                    
                page.wait_for_timeout(5000)
                self.status["state"] = "running"
                
            # Step 6: Verify portal home page load & child profiles ("Byron")
            self.log("Waiting for post-login redirection to portal home...")
            try:
                page.wait_for_selector("span:has-text('Actions'), h1:has-text('Byron')", timeout=35000)
            except Exception:
                pass
            page.wait_for_timeout(2000)
            
            # Check for error elements on SSO form
            error_el = page.locator("span.ulp-input-error-message, div.alert-danger, span#error-element-password").first
            if error_el.count() > 0 and error_el.is_visible():
                err_text = error_el.inner_text().strip()
                raise Exception(f"Authentication failed: {err_text}")
                
            self.log(f"Authenticated state verified! Current URL: {page.url}")

    def verify_imported_session(self, update_progress_cb: Optional[Callable[[str, int], None]] = None) -> List[Dict[str, str]]:
        """
        Verifies an imported session by launching Playwright with storage_state.json,
        streaming horizontal desktop JPEGs via self.latest_preview_b64, and dynamically
        waiting up to 180 seconds (3 minutes) for portal DOM elements to load.
        """
        self.status["state"] = "running"
        self.status["current_step"] = "Connecting to Bright Horizons portal"
        self.log("Verifying imported session authentication...")
        
        user_data_dir = self.tenant_storage.user_data_dir
        state_file = os.path.join(user_data_dir, "storage_state.json")
        
        if not os.path.exists(state_file):
            raise Exception("No session state file found to verify.")
            
        ensure_xvfb_display(1280, 720)
        
        with sync_playwright() as p:
            args = [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-size=1280,720"
            ]
            
            try:
                browser = p.chromium.launch(headless=False, channel="chrome", args=args, ignore_default_args=["--enable-automation"])
            except Exception:
                browser = p.chromium.launch(headless=False, args=args, ignore_default_args=["--enable-automation"])
                
            context = browser.new_context(storage_state=state_file, viewport={"width": 1280, "height": 720})
            page = context.new_page()
            self._active_page = page
            
            self.log("Navigating to https://familyinfocenter.brighthorizons.com/home...")
            page.goto("https://familyinfocenter.brighthorizons.com/home", wait_until="domcontentloaded")
            
            self.latest_preview_b64 = capture_compressed_b64_frame(page, 1280, 720)
            
            start_time = time.time()
            max_timeout = 180 # 3 minutes total timeout
            authenticated = False
            children = []
            
            while time.time() - start_time < max_timeout:
                self.latest_preview_b64 = capture_compressed_b64_frame(page, 1280, 720) or self.latest_preview_b64
                
                try:
                    current_url = page.url
                    
                    # Check for unauthenticated redirect to login
                    if "okta/login" in current_url or "auth0" in current_url:
                        try:
                            body = page.locator("body").inner_text()
                            if "Log In" in body or "Sign In" in body:
                                context.close()
                                self._active_page = None
                                raise Exception("Session expired or redirected to login page.")
                        except Exception as e:
                            if "Session expired" in str(e): raise e
                            
                    # Check for portal DOM elements (Actions spans or child profile cards)
                    actions_spans = page.locator("span", has_text="Actions")
                    if actions_spans.count() > 0:
                        authenticated = True
                        break
                except Exception as err:
                    if "Session expired" in str(err):
                        raise err
                    # Execution context destroyed while page is navigating; safely retry next tick
                    pass
                    
                time.sleep(1.0)
                
            if not authenticated:
                context.close()
                browser.close()
                self._active_page = None
                raise Exception("Portal load timed out after 180 seconds. Please check session freshness.")
                
            self.log("Authenticated portal page verified! Discovering enrolled children...")
            children = self.discover_children(page, context)
            
            context.close()
            browser.close()
            self._active_page = None
            
            return children

    def verify_credentials(self, progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None) -> List[Dict[str, str]]:
        """
        Standalone pre-verification helper with progress callbacks and live Playwright screenshot capture.
        Validates credentials with Auth0 and auto-discovers children.
        """
        def update_progress(step: str, step_index: int, page: Optional[Page] = None, force_shot: bool = True):
            shot = None
            if page:
                try:
                    shot = capture_compressed_b64_frame(page)
                except Exception:
                    pass

            if progress_callback:
                progress_callback({
                    "step": step,
                    "step_index": step_index,
                    "screenshot": shot,
                    "url": getattr(self, "_current_url", "https://familyinfocenter.brighthorizons.com/home")
                })

        self.log("Starting credentials pre-verification check...")
        update_progress("Bypassing Cloudflare turnstile protection via FlareSolverr...", 1, None, force_shot=False)
        
        user_data_dir = self.tenant_storage.user_data_dir
        clean_user_data_locks(user_data_dir)
        clearance_cookies, solver_ua = self.solve_cloudflare_flaresolverr("https://familyinfocenter.brighthorizons.com/home")
        
        ensure_xvfb_display()
        clean_user_data_locks(user_data_dir)
        with sync_playwright() as p:
            args = [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--window-size=1280,720"
            ]
            context_kwargs = {
                "args": args,
                "ignore_default_args": ["--enable-automation"],
                "headless": False
            }
            if solver_ua:
                context_kwargs["user_agent"] = solver_ua
            else:
                context_kwargs["user_agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                
            context: BrowserContext = p.chromium.launch_persistent_context(
                user_data_dir,
                **context_kwargs
            )
            
            if clearance_cookies:
                formatted_cookies = []
                for c in clearance_cookies:
                    formatted_cookies.append({
                        "name": c["name"],
                        "value": c["value"],
                        "domain": c["domain"],
                        "path": c.get("path", "/"),
                        "secure": c.get("secure", False)
                    })
                context.add_cookies(formatted_cookies)
            
            page: Page = context.new_page()
            try:
                from playwright_stealth import Stealth
                Stealth().apply_stealth_sync(page)
            except Exception as e:
                self.log(f"Stealth application notice: {e}")
            
            try:
                self.log("Navigating to portal and authenticating credentials...")
                self._current_url = "https://familyinfocenter.brighthorizons.com/okta/login"
                
                page.goto("https://familyinfocenter.brighthorizons.com/okta/login", wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                update_progress("Authenticating with Bright Horizons SSO...", 2, page=page, force_shot=True)
                
                self.perform_login(page, update_progress_cb=lambda s, idx: update_progress(s, idx, page=page, force_shot=True))
                self._current_url = page.url
                update_progress("Authentication verified! Discovering enrolled children...", 3, page=page, force_shot=True)
                
                # Step 2: Auto-discover children
                children = self.discover_children(page, context)
                if not children:
                    config = self.tenant_storage.load_config()
                    children = config.get("children", [])
                    
                if not children:
                    update_progress("Verification failed: No child profiles found.", 3, page=page, force_shot=True)
                    raise Exception("Authentication succeeded, but no active child profiles were discovered for this account.")
                    
                update_progress("Verification complete!", 3, page=page, force_shot=True)
                return children

            except Exception as e:
                update_progress(f"Verification error: {e}", 3, page=page, force_shot=True)
                raise e
            finally:
                try: context.close()
                except Exception: pass

    def discover_children(self, page: Page, context: BrowserContext) -> List[Dict[str, str]]:
        """Discovers active children and their dependent_ids following Angular CDK rules in .agents/AGENTS.md."""
        children = []
        try:
            page.goto("https://familyinfocenter.brighthorizons.com/home", wait_until="domcontentloaded")
            try:
                page.wait_for_selector("span:has-text('Actions')", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(2000)
            
            # Find all Actions menu triggers
            actions_spans = page.locator("span", has_text="Actions").all()
            self.log(f"Found {len(actions_spans)} 'Actions' buttons on child cards.")
            
            for idx, span in enumerate(actions_spans):
                try:
                    # Get child name from h1 in parent card
                    card_name = span.evaluate("""(el) => {
                        let current = el;
                        while (current && current.tagName !== 'BODY') {
                            let h1 = current.querySelector('h1');
                            if (h1 && h1.textContent.trim()) return h1.textContent.trim();
                            current = current.parentElement;
                        }
                        return '';
                    }""")
                    
                    if not card_name:
                        continue
                        
                    given_name = card_name.split()[0].capitalize()
                    
                    # Click Actions span to open CDK overlay
                    span.click()
                    page.wait_for_timeout(1000)
                    
                    # Target specific dropdown item
                    mbd = page.locator("span.actions-menu-item-label", has_text="My Bright Day").first
                    mbd.wait_for(state="visible", timeout=3000)
                    
                    with context.expect_page() as new_page_info:
                        mbd.evaluate("(el) => (el.closest('a') || el.closest('button') || el).click()")
                        
                    new_page = new_page_info.value
                    new_page.wait_for_load_state("domcontentloaded", timeout=10000)
                    
                    m = re.search(r'dependent_id=([^&]+)', new_page.url)
                    if m:
                        dep_id = m.group(1)
                        children.append({"name": given_name, "dependent_id": dep_id})
                        self.log(f"Discovered child: {given_name} (dependent_id: {dep_id[:8]}...)")
                        
                    new_page.close()
                except Exception as e:
                    self.log(f"Skipped child card #{idx + 1} (may not have active enrollment): {e}")
                    
        except Exception as e:
            self.log(f"Child auto-discovery warning: {e}")
            
        return children

    def extract_child_feed(self, page: Page, context: BrowserContext, child: Dict[str, str]):
        """Navigates child timeline, handles timeframe links, and extracts all feed items."""
        child_name = child["name"]
        dep_id = child["dependent_id"]
        
        self.log(f"Processing feed for {child_name}...")
        url = f"https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id={dep_id}"
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        
        # Scrape timeframe links
        timeframe_lis = page.locator("li", has_text=re.compile(r'^[a-z]{3}\s+\d{4}$', re.IGNORECASE)).all()
        self.log(f"Found {len(timeframe_lis)} timeframe month links for {child_name}.")
        
        self.status["current_child"] = child_name
        manifest = self.tenant_storage.load_manifest()
        
        for tf_li in timeframe_lis:
            if self._cancelled:
                self.log("Extraction cancelled by user.")
                return

            tf_text = tf_li.inner_text().strip()
            self.status["current_month"] = tf_text
            self.log(f"Navigating to timeframe: {tf_text}...")
            
            # Click inner div.tile (rule 2.A in AGENTS.md)
            tile = tf_li.locator("div.tile.pointable").first
            if tile.count() > 0:
                tile.click()
            else:
                tf_li.click()
                
            page.wait_for_timeout(3000)
            
            # Scroll to trigger lazy loading
            self.scroll_and_load(page)
            
            # Scope timeline search inside left panel (rule 2.B in AGENTS.md)
            timeline = page.locator("div.well.left-panel.pull-left")
            feed_items = timeline.locator("ul.thumbnails li").all() if timeline.count() > 0 else page.locator("ul.thumbnails li").all()
            
            self.log(f"Extracted {len(feed_items)} posts from timeframe {tf_text}.")
            
            for item in feed_items:
                if self._cancelled:
                    self.log("Extraction cancelled by user.")
                    return

                try:
                    fancybox = item.locator("a.fancybox").first
                    if fancybox.count() == 0:
                        continue
                        
                    href = fancybox.get_attribute("href") or ""
                    
                    # Video post handling (rule 2.C in AGENTS.md)
                    if href.startswith("#") or "obj_attachment" not in href:
                        pointable_tile = item.locator("div.tile.pointable").first
                        style = pointable_tile.get_attribute("style") or "" if pointable_tile.count() > 0 else ""
                        match = re.search(r'url\([\'"]?([^\'"]+)[\'"]?\)', style)
                        if match:
                            href = match[1]
                            
                    m_obj = re.search(r'obj=([^&]+)', href)
                    if not m_obj:
                        continue
                    obj_id = m_obj.group(1)
                    
                    # Check incremental sync stop condition
                    existing_entry = False
                    for m_id, entry in manifest.items():
                        if entry.get("obj_id") == obj_id:
                            existing_entry = True
                            break
                            
                    if existing_entry and self.sync_mode == "incremental":
                        self.log(f"Incremental sync hit existing obj_id {obj_id[:8]}... Stopping child feed scan.")
                        return

                    # Parse date overlay
                    overlay_span = item.locator("span.name span").first
                    date_text = overlay_span.inner_text().strip() if overlay_span.count() > 0 else ""
                    date_str = parse_date(date_text, tf_text)
                    self.status["current_date"] = date_str

                    # Check Custom Start Date condition
                    if self.start_date and date_str < self.start_date:
                        self.log(f"Post date {date_str} is before custom start date {self.start_date}. Skipping.")
                        continue
                        
                    # Extract full res URL
                    download_url = f"https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj={obj_id}&key={obj_id}"
                    
                    # Parse date overlay
                    overlay_span = item.locator("span.name span").first
                    date_text = overlay_span.inner_text().strip() if overlay_span.count() > 0 else ""
                    date_str = parse_date(date_text, tf_text)
                    
                    # Fetch file bytes via Playwright request
                    response = page.request.get(download_url)
                    if response.status != 200:
                        continue
                        
                    file_bytes = response.body()
                    mime_type = response.headers.get("content-type", "image/jpeg")
                    ext = detect_extension(file_bytes, mime_type)
                    
                    orig_filename = f"{child_name} {date_str} ({obj_id[:6]}).{ext}"
                    comment_text = f"Bright Horizons photo for {child_name} on {date_str}"
                    
                    # Save to tenant storage
                    saved_entry = self.tenant_storage.add_media_entry(
                        obj_id=obj_id,
                        child=child_name,
                        date_str=date_str,
                        original_filename=orig_filename,
                        comment=comment_text,
                        file_bytes=file_bytes,
                        mime_type=mime_type
                    )
                    
                    # Set Eastern Time timestamp (rule 4 in AGENTS.md)
                    abs_path = os.path.join(self.tenant_storage.tenant_dir, saved_entry["storage_path"])
                    set_eastern_timestamp(abs_path, date_str)
                    
                    self.status["files_downloaded"] += 1
                    self.log(f"Downloaded photo: {orig_filename}")
                    
                except Exception as item_err:
                    self.log(f"Failed parsing item: {item_err}")

    def scroll_and_load(self, page: Page):
        """Scrolls feed down iteratively to trigger lazy loading."""
        for _ in range(3):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            page.wait_for_timeout(2000)
            # Shake scroll
            page.evaluate("window.scrollBy(0, -600);")
            page.wait_for_timeout(500)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            page.wait_for_timeout(1000)

def parse_date(date_text: str, timeframe_text: str) -> str:
    """Parses date string into YYYY-MM-DD format using timeframe_text year context."""
    now = datetime.now()
    
    # Extract year from timeframe_text (e.g. "jun 2024" -> 2024)
    tf_year = None
    if timeframe_text:
        m_tf = re.search(r'\b(20\d{2})\b', timeframe_text)
        if m_tf:
            tf_year = int(m_tf.group(1))

    if not date_text:
        year_val = tf_year or now.year
        return f"{year_val:04d}-{now.month:02d}-{now.day:02d}"

    m = re.search(r'(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?', date_text)
    if m:
        month, day, year = m.groups()
        if not year:
            year = tf_year or now.year
        else:
            year = int(year)
            if year < 100: year += 2000
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

    year_val = tf_year or now.year
    return f"{year_val:04d}-{now.month:02d}-{now.day:02d}"

def detect_extension(file_bytes: bytes, content_type: str) -> str:
    """Inspects magic bytes to determine file extension."""
    if file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    elif file_bytes.startswith(b"\xff\xd8\xff"):
        return "jpg"
    elif b"ftypmp4" in file_bytes[:32] or b"ftypisom" in file_bytes[:32]:
        return "mp4"
    elif b"ftypqt" in file_bytes[:32]:
        return "mov"
    if "png" in content_type: return "png"
    if "mp4" in content_type: return "mp4"
    if "video" in content_type: return "mp4"
    return "jpg"

def set_eastern_timestamp(file_path: str, date_str: str):
    """Sets file mtime/atime to 10:00 AM America/New_York time (rule 4 in AGENTS.md)."""
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=10, minute=0, second=0)
        dt_et = dt.replace(tzinfo=ZoneInfo("America/New_York"))
        epoch = dt_et.timestamp()
        os.utime(file_path, (epoch, epoch))
    except Exception as e:
        print(f"Timestamp set error: {e}")
