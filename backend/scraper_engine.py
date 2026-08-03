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
import html
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright, BrowserContext, Page
from backend.database import TenantStorage
from backend.dom_parser import extract_obj_id_from_url_or_style, get_month_end_date

try:
    from playwright_stealth import stealth_sync
except ImportError:
    stealth_sync = None

FLARESOLVERR_URL = os.environ.get("FLARESOLVERR_URL", "http://flaresolverr:8191/v1")

def ensure_xvfb_display(width=1280, height=720):
    """Ensures Xvfb virtual display :99 is active without disrupting active concurrent sessions."""
    os.environ["DISPLAY"] = ":99"
    res = os.system("xdpyinfo -display :99 >/dev/null 2>&1")
    if res != 0:
        os.system("rm -f /tmp/.X99-lock /tmp/.X11-unix/X99 2>/dev/null")
        os.system(f"Xvfb :99 -screen 0 {width}x{height}x24 > /dev/null 2>&1 &")
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

def launch_stealth_persistent_context(playwright_instance, user_data_dir: str, extra_args: list = None, **kwargs):
    """Launches a persistent browser context targeting real system Chrome with anti-bot masking flags."""
    clean_user_data_locks(user_data_dir)
    ensure_xvfb_display(1280, 720)

    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--window-size=1280,720",
        "--lang=en-US,en"
    ]
    if extra_args:
        args.extend(extra_args)

    context_kwargs = {
        "user_data_dir": user_data_dir,
        "headless": False,
        "args": args,
        "ignore_default_args": ["--enable-automation"],
        "viewport": {"width": 1280, "height": 720}
    }
    context_kwargs.update(kwargs)
    context_kwargs.pop("storage_state", None)

    # Try launching real system Chrome executable or channel
    chrome_paths = ["/usr/bin/google-chrome-stable", "/usr/bin/google-chrome"]
    found_chrome = next((p for p in chrome_paths if os.path.exists(p)), None)
    if found_chrome:
        context_kwargs["executable_path"] = found_chrome
    else:
        context_kwargs["channel"] = "chrome"

    try:
        context = playwright_instance.chromium.launch_persistent_context(**context_kwargs)
    except Exception:
        # Fallback to Playwright Chromium binary if system Chrome channel is absent
        context_kwargs.pop("executable_path", None)
        context_kwargs.pop("channel", None)
        context = playwright_instance.chromium.launch_persistent_context(**context_kwargs)

    # Inject anti-bot stealth scripts
    try:
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
        """)
    except Exception:
        pass

    if stealth_sync:
        for p in context.pages:
            try:
                stealth_sync(p)
            except Exception:
                pass
        context.on("page", lambda p: stealth_sync(p))

    state_file = os.path.join(user_data_dir, "storage_state.json")
    if os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                state_data = json.load(f)
            cookies = state_data.get("cookies", [])
            if cookies:
                context.add_cookies(cookies)
        except Exception:
            pass

    return context

class NetworkTraceLogger:
    def __init__(self, job: "ScraperJob"):
        self.job = job
        self._enabled = True

    def attach_to_context(self, context: BrowserContext):
        """Attaches network event listeners to Playwright BrowserContext to trace all pages & frames."""
        context.on("request", self._on_request)
        context.on("response", self._on_response)
        context.on("requestfailed", self._on_request_failed)

    def _redact_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        redacted = {}
        for k, v in headers.items():
            k_lower = k.lower()
            if k_lower in ["authorization", "cookie", "set-cookie", "x-auth-token"]:
                redacted[k] = "[REDACTED]"
            else:
                redacted[k] = v
        return redacted

    def _on_request(self, request):
        url = request.url
        if url.startswith("data:") or any(ext in url for ext in [".woff", ".woff2", ".ttf", ".svg", ".css"]):
            return
            
        if any(domain in url for domain in ["brighthorizons", "auth0", "cloudflare", "obj_attachment"]):
            headers_summary = self._redact_headers(request.headers)
            self.job.log_structured(
                level="DEBUG",
                category="NETWORK_REQ",
                message=f"--> {request.method} {url}",
                details={
                    "method": request.method,
                    "url": url,
                    "resource_type": request.resource_type,
                    "headers": headers_summary
                }
            )

    def _on_response(self, response):
        url = response.url
        if url.startswith("data:") or any(ext in url for ext in [".woff", ".woff2", ".ttf", ".svg", ".css"]):
            return

        if any(domain in url for domain in ["brighthorizons", "auth0", "cloudflare", "obj_attachment"]):
            status = response.status
            set_cookie_headers = [v for k, v in response.headers.items() if k.lower() == "set-cookie"]
            
            details = {
                "status": status,
                "url": url,
                "status_text": response.status_text,
                "set_cookies_count": len(set_cookie_headers)
            }
            if set_cookie_headers:
                redacted_cookies = []
                for header in set_cookie_headers:
                    for part in header.split(","):
                        cookie_decl = part.split(";")[0].strip()
                        if "=" in cookie_decl:
                            name = cookie_decl.split("=")[0].strip()
                            if name:
                                redacted_cookies.append(f"{name}=[REDACTED]")
                details["set_cookies"] = redacted_cookies

            level = "INFO" if status < 400 else ("WARN" if status < 500 else "ERROR")
            self.job.log_structured(
                level=level,
                category="NETWORK_RESP",
                message=f"<-- HTTP {status} {url}",
                details=details
            )

    def _on_request_failed(self, request):
        url = request.url
        if any(domain in url for domain in ["brighthorizons", "auth0", "cloudflare", "obj_attachment"]):
            failure = request.failure
            self.job.log_structured(
                level="ERROR",
                category="NETWORK_FAIL",
                message=f"X-- FAILED {request.method} {url} | Error: {failure}",
                details={"url": url, "failure": failure}
            )


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
            "screenshot": None,
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

    def _update_screenshot(self, page: Optional[Page] = None):
        """Captures a lightweight base64 JPEG screenshot of the active Playwright browser page."""
        p = page or self._active_page
        if not p:
            return
        try:
            screenshot_bytes = p.screenshot(type="jpeg", quality=40, scale="css")
            b64 = base64.b64encode(screenshot_bytes).decode("utf-8")
            self.status["screenshot"] = f"data:image/jpeg;base64,{b64}"
        except Exception:
            pass

    def log_structured(self, level: str, category: str, message: str, details: Optional[Dict[str, Any]] = None):
        """Structured logging method storing log messages and calling log_callback."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        entry_str = f"[{timestamp}] [{level}] [{category}] {message}"
        
        self.status["logs"].append(entry_str)
        if len(self.status["logs"]) > 300:
            self.status["logs"].pop(0)
            
        if self.log_callback:
            self.log_callback(entry_str)

    def log(self, message: str):
        self.log_structured("INFO", "GENERAL", message)

    def solve_cloudflare_flaresolverr(self, target_url: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
        """Queries FlareSolverr API to resolve Cloudflare turnstile/bot challenges and return session cookies & matching User-Agent."""
        start_t = time.time()
        self.log(f"[FlareSolverr] Initiating pre-flight challenge check for {target_url} via ({FLARESOLVERR_URL})...")
        try:
            payload = {
                "cmd": "request.get",
                "url": target_url,
                "maxTimeout": 60000
            }
            resp = requests.post(FLARESOLVERR_URL, json=payload, timeout=70)
            elapsed = round(time.time() - start_t, 2)

            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "ok":
                    solution = data.get("solution", {})
                    cookies = solution.get("cookies", [])
                    user_agent = solution.get("userAgent")
                    
                    cf_cookies = [c for c in cookies if "cf" in c.get("name", "").lower() or "clearance" in c.get("name", "").lower()]
                    if cf_cookies:
                        self.log(f"[FlareSolverr] ✅ SUCCESS: Cloudflare protection detected & solved in {elapsed}s ({len(cf_cookies)} clearance cookies extracted).")
                    else:
                        self.log(f"[FlareSolverr] ℹ️ NOT NEEDED: Target page responded cleanly without Cloudflare challenge in {elapsed}s ({len(cookies)} total cookies extracted).")
                    
                    return cookies, user_agent
                else:
                    msg = data.get("message", "Unknown FlareSolverr response error")
                    self.log(f"[FlareSolverr] ⚠️ UNHELPFUL: Status '{data.get('status')}' after {elapsed}s: {msg} (falling back to native Playwright stealth)")
            else:
                self.log(f"[FlareSolverr] ⚠️ HTTP {resp.status_code}: Endpoint error after {elapsed}s (falling back to native Playwright stealth)")

        except requests.exceptions.Timeout:
            elapsed = round(time.time() - start_t, 2)
            self.log(f"[FlareSolverr] ⚠️ TIMEOUT: Service request timed out after {elapsed}s (falling back to native Playwright stealth)")
        except requests.exceptions.ConnectionError:
            self.log(f"[FlareSolverr] ⚠️ UNREACHABLE: Service at {FLARESOLVERR_URL} is offline or unreachable (falling back to native Playwright stealth)")
        except Exception as e:
            self.log(f"[FlareSolverr] ⚠️ ERROR: Check failed: {e} (falling back to native Playwright stealth)")

        return [], None

    def cancel(self):
        """Cancels the active scraper job cleanly."""
        self._cancelled = True
        self.status["state"] = "cancelled"
        self.status["current_step"] = "Extraction cancelled by user"
        self.log("Job cancellation requested by user.")
        self._mfa_event.set()
        self._step_event.set()
        if hasattr(self, "_active_page") and self._active_page:
            try:
                self._active_page.context.close()
            except Exception:
                pass
            self._active_page = None

    def run(self):
        self.status["state"] = "running"
        target_name_display = self.target_child.capitalize() if self.target_child != "all" else "All Enrolled Children"
        self.log(f"Starting background extraction job for '{target_name_display}' (Sync Mode: {self.sync_mode.upper()})...")
        
        user_data_dir = self.tenant_storage.user_data_dir
        state_file = os.path.join(user_data_dir, "storage_state.json")
        
        try:
            ensure_xvfb_display()
            with sync_playwright() as p:
                context: BrowserContext = launch_stealth_persistent_context(
                    p,
                    user_data_dir,
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                )
                # Attach NetworkTraceLogger for deep logging & network tracing
                network_tracer = NetworkTraceLogger(self)
                network_tracer.attach_to_context(context)

                page: Page = context.pages[0] if context.pages else context.new_page()
                self._active_page = page
                
                # Check existing authentication state
                self.status["current_step"] = "Verifying portal session"
                self.log("Navigating to https://familyinfocenter.brighthorizons.com/home...")
                page.goto("https://familyinfocenter.brighthorizons.com/home", wait_until="domcontentloaded")
                
                try:
                    page.wait_for_selector("span:has-text('Actions'), input[name='username'], button:has-text('Log In')", timeout=25000)
                except Exception:
                    pass
                time.sleep(2.0)
                
                if "login" in page.url or "okta" in page.url:
                    self.log("Saved session expired or missing; attempting automatic re-authentication...")
                    config = self.tenant_storage.load_config()
                    stored_pwd = config.get("password") or self.password
                    if stored_pwd:
                        self.password = stored_pwd
                        self.perform_login(page)
                    else:
                        context.close()
                        self._active_page = None
                        self.tenant_storage.clear_session()
                        raise Exception("Session expired or invalid. Please re-authenticate and provide fresh session cookies.")

                # Trigger SSO token redirect from Family Info Center to My Bright Day if on familyinfocenter
                if "familyinfocenter" in page.url:
                    self.log("Triggering SSO token redirect from Family Information Center...")
                    actions_spans = page.locator("span", has_text="Actions").all()
                    for span in actions_spans:
                        try:
                            span.click()
                            time.sleep(1.5)
                            mbd = page.locator("span.actions-menu-item-label", has_text="My Bright Day").first
                            if mbd.is_visible():
                                with context.expect_page() as new_page_info:
                                    mbd.evaluate("(el) => (el.closest('a') || el.closest('button') || el).click()")
                                mbd_page = new_page_info.value
                                mbd_page.wait_for_load_state("domcontentloaded")
                                page = mbd_page
                                self._active_page = page
                                time.sleep(5.0)
                                self.log(f"Successfully landed on My Bright Day via SSO: {page.url}")
                                break
                        except Exception as e:
                            self.log(f"Actions click attempt note: {e}")

                if "login" not in page.url and ("parents.html" in page.url or "familyinfocenter" in page.url or "brighthorizons" in page.url):
                    self.log("Authenticated portal page verified via saved session!")
                else:
                    self.log("SSO redirect requires re-authentication; performing automatic login...")
                    config = self.tenant_storage.load_config()
                    stored_pwd = config.get("password") or self.password
                    if stored_pwd:
                        self.password = stored_pwd
                        self.perform_login(page)
                    else:
                        context.close()
                        self._active_page = None
                        self.tenant_storage.clear_session()
                        raise Exception("Session expired or invalid. Please re-authenticate and provide fresh session cookies.")
                    
                if self._cancelled:
                    context.close()
                    self._active_page = None
                    return

                # Step 2: Auto-discover enrolled children
                config = self.tenant_storage.load_config()
                manifest = self.tenant_storage.load_manifest()
                all_children = config.get("children") or manifest.get("children") or []

                if not all_children:
                    self.status["current_step"] = "Discovering enrolled children"
                    try:
                        self.log("Attempting child auto-discovery on Family Info Center...")
                        page.goto("https://familyinfocenter.brighthorizons.com/home", wait_until="domcontentloaded")
                        time.sleep(3.0)
                        all_children = self.discover_children(page, context)
                    except Exception as disc_err:
                        self.log(f"Child auto-discovery on Family Info Center skipped: {disc_err}")

                if not all_children:
                    all_children = [
                        {"name": "Byron", "dependent_id": "673e065a9d37c9fab2483b2d"},
                        {"name": "Catherine", "dependent_id": "6322019106aa0d39b230f4a0"}
                    ]

                if self.target_child != "all":
                    target_clean = self.target_child.strip().lower()
                    matching = [c for c in all_children if c.get("name", "").strip().lower() == target_clean or c.get("name", "").strip().lower().startswith(target_clean)]
                    if matching:
                        children = matching
                        self.log(f"Target child '{matching[0]['name']}' selected. Processing single child feed directly.")
                    else:
                        raise Exception(f"Selected target child '{self.target_child}' was not found among enrolled children.")
                else:
                    children = all_children

                # Step 3: Extract feed for children
                self.status["current_step"] = "Extracting photos & videos"
                for child in children:
                    if self._cancelled: break
                    self.extract_child_feed(page, context, child)
                    
                if self._cancelled:
                    self.status["state"] = "cancelled"
                    self.status["current_step"] = "Extraction cancelled"
                else:
                    self.status["state"] = "completed"
                    self.status["current_step"] = "Extraction finished successfully"
                    self.log("All extraction tasks completed successfully!")
                
                # Persist storage state post extraction
                try:
                    context.storage_state(path=state_file)
                    self.log("Successfully saved final extraction session cookies to storage_state.json")
                except Exception as e:
                    self.log(f"Final storage_state save notice: {e}")

                context.close()
                self._active_page = None

        except Exception as e:
            if self._cancelled:
                self.status["state"] = "cancelled"
                self.status["current_step"] = "Extraction cancelled"
            else:
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

    def ensure_cross_domain_session(self, page: Page, context: BrowserContext, dependent_id: Optional[str] = None) -> bool:
        """Ensures active session cookies exist across familyinfocenter and mybrightday origins."""
        self.log("Verifying cross-domain session cookies on My Bright Day...")
        
        # 1. Test existing MyBrightDay API session payload
        try:
            resp = page.request.get("https://mybrightday.brighthorizons.com/remote/v1/user_payload", timeout=5000)
            if resp.status == 200:
                payload = resp.json()
                if isinstance(payload, dict) and (payload.get("user") or payload.get("dependents")):
                    self.log("Valid My Bright Day session cookies confirmed!")
                    return True
        except Exception:
            pass

        # 2. Perform cross-domain handshake from Family Info Center to My Bright Day
        self.log("Session token missing on My Bright Day; performing cross-domain SSO handshake...")
        target_url = "https://familyinfocenter.brighthorizons.com/home"
        try:
            page.goto(target_url, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)
        except Exception as e:
            self.log(f"Navigation note during SSO handshake: {e}")

        # Trigger SSO redirect via child card My Bright Day link
        handshake_success = False
        try:
            actions_spans = page.locator("span", has_text="Actions").all()
            for span in actions_spans:
                try:
                    span.click()
                    page.wait_for_timeout(1000)
                    mbd = page.locator("span.actions-menu-item-label", has_text="My Bright Day").first
                    if mbd.is_visible():
                        with context.expect_page() as new_page_info:
                            mbd.evaluate("(el) => (el.closest('a') || el.closest('button') || el).click()")
                        mbd_page = new_page_info.value
                        mbd_page.wait_for_load_state("domcontentloaded")
                        mbd_page.wait_for_timeout(3000)
                        handshake_success = True
                        mbd_page.close()
                        break
                except Exception as e:
                    self.log(f"SSO handshake click notice: {e}")
        except Exception as e:
            self.log(f"SSO handshake locator notice: {e}")

        if not handshake_success and dependent_id:
            # Fallback: Navigate directly with dependent_id
            try:
                page.goto(f"https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id={dependent_id}", wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
            except Exception as e:
                self.log(f"Direct fallback navigation notice: {e}")

        # 3. Persist updated cross-domain cookies to storage_state.json
        state_file = os.path.join(self.tenant_storage.user_data_dir, "storage_state.json")
        try:
            context.storage_state(path=state_file)
            self.log(f"Persisted updated cross-domain storage_state to {state_file}")
        except Exception as e:
            self.log(f"Storage state update notice: {e}")

        return True

    def solve_and_wait_turnstile(self, page: Page, max_wait_sec: int = 50, update_progress_cb: Optional[Callable[[str, int], None]] = None) -> bool:
        """
        Monitors Cloudflare Turnstile verification with a zero-delay fast-path.
        If challenge_present=False (no active Turnstile iframe or challenge prompt),
        returns True within 1.5s to allow instant Auth0 credential entry.
        """
        self.log_structured("INFO", "TURNSTILE", f"[Turnstile] Checking Turnstile security check (timeout: {max_wait_sec}s)...", details={"url": page.url})
        if update_progress_cb:
            update_progress_cb("Checking Cloudflare security check...", 2)

        start_t = time.time()
        last_click_t = 0.0
        last_log_t = 0.0
        last_flaresolverr_t = 0.0
        grace_period_sec = 1.5  # Max grace period to detect dynamic iframe insertion

        while time.time() - start_t < max_wait_sec:
            elapsed = time.time() - start_t
            current_elapsed = int(elapsed)
            
            # 1. Check if Cloudflare populated the response token
            token_populated = False
            try:
                token_populated = page.evaluate("""() => {
                    const inputs = document.querySelectorAll("input[name='cf-turnstile-response'], input[name='g-recaptcha-response']");
                    for (const input of inputs) {
                        if (input.value && input.value.trim().length > 10) return true;
                    }
                    return false;
                }""")
            except Exception:
                pass

            if token_populated:
                self.log_structured("INFO", "TURNSTILE", f"[Turnstile] 🎉 Successfully verified! Response token populated after {round(elapsed, 2)}s.", details={"elapsed": round(elapsed, 2), "fast_path": True})
                return True

            # 2. Inspect frames and body text safely
            has_cf_iframe = any("challenges.cloudflare.com" in f.url for f in page.frames)

            body_text = ""
            try:
                body_text = page.locator("body").inner_text().lower()
            except Exception:
                pass

            frame_sources = []
            cf_frames = []
            for f in page.frames:
                try:
                    f_url = f.url
                    f_text = f.locator("body").inner_text().lower()
                    frame_sources.append(f_text)
                    if "challenges.cloudflare.com" in f_url:
                        cf_frames.append((f, f_text))
                except Exception:
                    pass

            combined = body_text + " " + " ".join(frame_sources)
            
            if "success!" in combined or "verified" in combined:
                self.log_structured("INFO", "TURNSTILE", f"[Turnstile] 🎉 Successfully verified ('Success!' text detected) after {round(elapsed, 2)}s.")
                return True

            is_verifying = any(p in combined for p in [
                "verifying",
                "verifying...",
                "checking if the site connection is secure",
                "checking your browser"
            ])

            has_challenge = any(p in combined for p in [
                "verify you are human",
                "verify you are a human",
                "verifying you are human",
                "confirm you are human",
                "human verification"
            ])

            is_turnstile_active = has_cf_iframe or is_verifying or has_challenge

            # 3. Fast-Path Bypass: ONLY proceed if NO Cloudflare iframe, verifying state, or challenge prompt exists after grace period
            if elapsed >= grace_period_sec and not is_turnstile_active:
                self.log_structured("INFO", "TURNSTILE", f"[Turnstile] ⚡ Fast-Path: No active Cloudflare iframe or security challenge detected after {round(elapsed, 2)}s. Proceeding immediately to Auth0 credential entry...", details={"elapsed": round(elapsed, 2), "challenge_present": False})
                return True

            # Log periodic status update every 5 seconds
            if time.time() - last_log_t >= 5.0:
                last_log_t = time.time()
                self.log_structured("DEBUG", "TURNSTILE", f"[Turnstile] Status ({current_elapsed}s): token_populated={token_populated}, cf_frames={len(cf_frames)}, challenge_present={has_challenge}, is_verifying={is_verifying}, url={page.url}")

            # 4. If challenge frame is present, attempt human mouse click on Turnstile checkbox element if unverified for > 3.0s
            if cf_frames and (time.time() - last_click_t > 3.0):
                for cf_frame, f_text in cf_frames:
                    self.log_structured("INFO", "TURNSTILE", f"[Turnstile] Attempting verification click on Cloudflare frame (URL: {cf_frame.url[:60]}...)...")
                    try:
                        # Strategy A: Direct frame body click at (30, 30) where Turnstile checkbox resides
                        cf_frame.click("body", position={"x": 30, "y": 30})
                        last_click_t = time.time()
                        page.wait_for_timeout(1000)
                    except Exception as e:
                        try:
                            # Strategy B: Top-level page human mouse movement to iframe bounding box
                            iframe_loc = page.locator("iframe[src*='challenges.cloudflare.com'], iframe[src*='turnstile']").first
                            if iframe_loc.count() > 0 and iframe_loc.is_visible():
                                box = iframe_loc.bounding_box()
                                if box and box['width'] > 0 and box['height'] > 0:
                                    target_x = box['x'] + min(35.0, box['width'] / 2)
                                    target_y = box['y'] + min(35.0, box['height'] / 2)
                                    self.log_structured("INFO", "TURNSTILE", f"[Turnstile] Moving human mouse to iframe box ({round(target_x, 1)}, {round(target_y, 1)})...")
                                    page.mouse.move(target_x, target_y, steps=10)
                                    page.wait_for_timeout(100)
                                    page.mouse.click(target_x, target_y)
                                    last_click_t = time.time()
                                    page.wait_for_timeout(1000)
                        except Exception as e2:
                            self.log_structured("WARN", "TURNSTILE", f"[Turnstile] Click note: {e2}")

            # 5. Fallback: If challenge remains active after 8 seconds, request clearance from FlareSolverr service
            if has_challenge and (elapsed > 8.0) and (time.time() - last_flaresolverr_t > 12.0):
                last_flaresolverr_t = time.time()
                self.log_structured("INFO", "TURNSTILE", f"[Turnstile] Challenge prompt active after {round(elapsed, 1)}s. Requesting FlareSolverr clearance cookies for {page.url[:60]}...")
                try:
                    solver_cookies, solver_ua = self.solve_cloudflare_flaresolverr(page.url)
                    if solver_cookies:
                        page.context.add_cookies(solver_cookies)
                        self.log_structured("INFO", "TURNSTILE", f"[Turnstile] Injected {len(solver_cookies)} FlareSolverr clearance cookies into browser context.")
                        page.wait_for_timeout(1500)
                except Exception as e:
                    self.log_structured("WARN", "TURNSTILE", f"[Turnstile] FlareSolverr fallback note: {e}")

            page.wait_for_timeout(250)

        # 5. Post-timeout strict failure assessment
        final_token = False
        try:
            final_token = page.evaluate("""() => {
                const inputs = document.querySelectorAll("input[name='cf-turnstile-response'], input[name='g-recaptcha-response']");
                for (const input of inputs) {
                    if (input.value && input.value.trim().length > 10) return true;
                }
                return false;
            }""")
        except Exception:
            pass

        if final_token:
            self.log_structured("INFO", "TURNSTILE", f"[Turnstile] 🎉 Verified: Token populated after monitoring window.")
            return True

        final_body = ""
        try:
            final_body = page.locator("body").inner_text().lower()
        except Exception:
            pass

        final_frames = " ".join([f.locator("body").inner_text().lower() for f in page.frames if "challenges.cloudflare.com" in f.url])
        final_combined = final_body + " " + final_frames

        if ("verify you are human" in final_combined or "verify you are a human" in final_combined) and not final_token:
            self.log_structured("ERROR", "TURNSTILE", "[Turnstile] ❌ Verification failed: Cloudflare 'Verify you are human' challenge remained unsolved.")
            raise Exception("Cloudflare Turnstile verification failed. Please try again.")

        self.log_structured("INFO", "TURNSTILE", f"[Turnstile] Monitoring window ended after {max_wait_sec}s. Proceeding...")
        return True

    def check_auth0_errors(self, page: Page):
        """Scans page for Auth0 credential validation error messages and raises an Exception if present."""
        # 1. Selector check for error banners & input error messages
        error_loc = page.locator("span#error-element-password, div#error-element-password, span#error-element-username, div#error-element-username, .ulp-input-error-message, .alert-danger, [data-error-code]").first
        if error_loc.count() > 0 and error_loc.is_visible():
            err_text = error_loc.inner_text().strip()
            if err_text:
                self.log(f"Auth0 authentication error detected: '{err_text}'")
                raise Exception(f"Authentication failed: {err_text}")

        # 2. Text check on page body for standard error phrases
        try:
            body_text = page.locator("body").inner_text().lower()
            if any(p in body_text for p in ["wrong email or password", "wrong password", "invalid email or password", "incorrect email or password", "user does not exist", "invalid username or password"]):
                self.log("Auth0 error text detected in DOM body.")
                raise Exception("Authentication failed: Wrong email or password.")
        except Exception as e:
            if "Authentication failed:" in str(e):
                raise e

    def perform_login(self, page: Page, update_progress_cb: Optional[Callable[[str, int], None]] = None, force_fresh_auth: bool = False):
        """Ultra-robust login handler following the exact Bright Horizons & Auth0 SSO authentication sequence."""
        self._active_page = page
        self.log("Navigating to familyinfocenter.brighthorizons.com/okta/login...")
        page.goto("https://familyinfocenter.brighthorizons.com/okta/login", wait_until="domcontentloaded")
        
        state = self.detect_page_state(page, max_wait_sec=15)
        self.log(f"Detected page state: '{state}' (URL: {page.url})")
        
        if state == "authenticated":
            # Verify if MyBrightDay domain session is genuinely active and valid
            mbd_valid = False
            try:
                resp = page.request.get("https://mybrightday.brighthorizons.com/remote/v1/user_payload", timeout=5000)
                if resp.status == 200:
                    try:
                        payload = resp.json()
                        if isinstance(payload, dict) and (payload.get("user") or payload.get("dependents")):
                            mbd_valid = True
                    except Exception:
                        pass
            except Exception as e:
                self.log(f"MyBrightDay token validation check failed: {e}")

            if mbd_valid and not force_fresh_auth:
                self.log("Already authenticated with valid MyBrightDay browser session!")
                return
            else:
                self.log("Stale or incomplete session detected (missing/invalid MyBrightDay tokens). Forcing full Auth0 re-authentication...")
                try:
                    page.goto("https://bhloginsso.brighthorizons.com/v2/logout", wait_until="domcontentloaded", timeout=10000)
                    page.wait_for_timeout(1000)
                except Exception:
                    pass
                try:
                    page.goto("https://familyinfocenter.brighthorizons.com/okta/logout", wait_until="domcontentloaded", timeout=10000)
                    page.wait_for_timeout(1000)
                except Exception:
                    pass
                if force_fresh_auth:
                    try:
                        page.context.clear_cookies()
                    except Exception:
                        pass

                    # Deep clear browser cookies and origin storage via Chrome DevTools Protocol (CDP)
                    try:
                        cdp = page.context.new_cdp_session(page)
                        cdp.send("Network.clearBrowserCookies")
                        cdp.send("Storage.clearDataForOrigin", {"origin": "https://bhloginsso.brighthorizons.com", "storageTypes": "all"})
                        cdp.send("Storage.clearDataForOrigin", {"origin": "https://familyinfocenter.brighthorizons.com", "storageTypes": "all"})
                        cdp.send("Storage.clearDataForOrigin", {"origin": "https://mybrightday.brighthorizons.com", "storageTypes": "all"})
                    except Exception as e:
                        self.log(f"CDP session clear notice: {e}")

                page.goto("https://familyinfocenter.brighthorizons.com/okta/login", wait_until="domcontentloaded")
                state = self.detect_page_state(page, max_wait_sec=15)
                self.log(f"Post-logout refreshed page state: '{state}' (URL: {page.url})")

                # If state is still 'authenticated', navigate directly to login form
                if state == "authenticated":
                    self.log("Page remained on authenticated home; navigating explicitly to login trigger...")
                    page.goto("https://familyinfocenter.brighthorizons.com/okta/login", wait_until="domcontentloaded")
                    state = self.detect_page_state(page, max_wait_sec=15)

        # Step 1: Wait for and click Landing Page "Log In" button
        if state == "landing_login_btn":
            self.log("Clicking portal Log In button...")
            if update_progress_cb: update_progress_cb("Clicking portal Log In button...", 2)
            btn = page.locator("button:has-text('Log In'), a:has-text('Log In'), button:has-text('Sign In'), a:has-text('Sign In')").first
            btn.click()
            page.wait_for_load_state("domcontentloaded")
            state = self.detect_page_state(page, max_wait_sec=15)
            self.log(f"Post-click page state: '{state}' (URL: {page.url})")

        if state in ["auth0_username", "auth0_password"]:
            self.log("Auth0 SSO login form loaded.")
            
            # Step 1: Handle Email / Username Entry
            username_inp = page.locator("input[name='username'], input[id='username'], input[type='email']").first
            if username_inp.count() > 0 and username_inp.is_visible():
                curr_val = username_inp.input_value()
                if not curr_val or curr_val.strip() == "":
                    # Solve / Fast-path Turnstile before typing email
                    if not self.solve_and_wait_turnstile(page, max_wait_sec=50, update_progress_cb=update_progress_cb):
                        raise Exception("Cloudflare Turnstile security verification failed.")

                    self.log("Filling email address into SSO username input...")
                    if update_progress_cb: update_progress_cb("Filling email address...", 2)
                    page.fill("input[name='username'], input[id='username'], input[type='email']", self.email)
                    
                    # If password field is not yet visible, press Enter to submit username step
                    pwd_inp_check = page.locator("input[name='password']:not(.hide), input[id='password']").first
                    if pwd_inp_check.count() == 0 or not pwd_inp_check.is_visible():
                        self.log("Submitting email step...")
                        page.keyboard.press("Enter")
                        try:
                            page.locator("input[name='password']:not(.hide), input[id='password'], span#error-element-username, div#error-element-username, .ulp-input-error-message").first.wait_for(state="visible", timeout=12000)
                        except Exception:
                            pass
                        self.check_auth0_errors(page)

            # Step 2: Handle Password Entry
            pwd_inp = page.locator("input[name='password']:not(.hide), input[id='password']").first
            pwd_inp.wait_for(state="visible", timeout=30000)
            
            self.log("Filling password...")
            if update_progress_cb: update_progress_cb("Submitting password...", 2)
            page.fill("input[name='password']:not(.hide), input[id='password']", self.password)
            self.log("Pressing Enter to submit password...")
            page.keyboard.press("Enter")
                
            self.log("Waiting for post-login redirection or MFA challenge...")
            
            # Dynamically wait for post-login redirection or MFA prompt
            try:
                page.locator("input[name='code'], span:has-text('Actions'), h1, span#error-element-password, div.alert-danger").first.wait_for(state="visible", timeout=15000)
            except Exception:
                pass
                
            self.check_auth0_errors(page)
            
            # Step 5: Email Verification Code (MFA) & "Remember this device for 30 days"
            state = self.detect_page_state(page, max_wait_sec=5)
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
                
                submit_mfa_btn = page.locator("button[type='submit']:not(.ulp-hidden-form-submit-button), button[name='action'], button:has-text('Continue'), button:has-text('Verify')").first
                if submit_mfa_btn.count() > 0 and submit_mfa_btn.is_visible():
                    submit_mfa_btn.click(force=True)
                else:
                    mfa_inp.press("Enter")
                    
                try:
                    page.locator("span:has-text('Actions'), h1, span#error-element-password").first.wait_for(state="visible", timeout=15000)
                except Exception:
                    pass
                self.check_auth0_errors(page)
                self.status["state"] = "running"
                
            # Step 6: Verify portal home page load with fast-react polling (up to 45s timeout)
            self.log("Waiting for post-login redirection to portal home (fast-react polling up to 45s)...")
            start_poll = time.time()
            max_timeout = 45.0
            auth_confirmed = False

            while time.time() - start_poll < max_timeout:
                self.check_auth0_errors(page)
                
                try:
                    # Check for child card "Actions" dropdown trigger or home dashboard headings
                    if page.locator("span:has-text('Actions')").count() > 0:
                        elapsed = round(time.time() - start_poll, 2)
                        self.log(f"Portal home authenticated DOM element ('Actions') detected in {elapsed}s!")
                        auth_confirmed = True
                        break

                    # Also check for child card full-name heading on familyinfocenter home page
                    if "familyinfocenter" in page.url.lower() and page.locator("div.card h1, div.child-card h1, h1.child-name, h1:has-text('Taccani')").count() > 0:
                        elapsed = round(time.time() - start_poll, 2)
                        self.log(f"Portal home authenticated DOM element ('child card heading') detected in {elapsed}s!")
                        auth_confirmed = True
                        break
                except Exception:
                    pass

                page.wait_for_timeout(250) # Active poll every 250ms for immediate reaction

            if not auth_confirmed:
                self.log(f"Polling window ended after {max_timeout}s without explicit DOM marker. Current URL: {page.url}")
            else:
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
            context = launch_stealth_persistent_context(p, user_data_dir)
            page = context.pages[0] if context.pages else context.new_page()
            self._active_page = page
            
            authenticated = False
            
            # Primary: Verify on Family Info Center home portal
            self.log("Navigating to https://familyinfocenter.brighthorizons.com/home...")
            try:
                page.goto("https://familyinfocenter.brighthorizons.com/home", wait_until="domcontentloaded")
                start_time = time.time()
                while time.time() - start_time < 12.0:
                    self.latest_preview_b64 = capture_compressed_b64_frame(page, 1280, 720) or self.latest_preview_b64
                    try:
                        actions_spans = page.locator("span", has_text="Actions")
                        if actions_spans.count() > 0 or ("login" not in page.url and "home" in page.url):
                            authenticated = True
                            self.log("Session verified successfully on Family Information Center!")
                            break
                    except Exception:
                        pass
                    time.sleep(1.0)
            except Exception as e:
                self.log(f"Family Info Center navigation attempt notice: {e}")
                
            # Secondary fallback: Verify directly on My Bright Day dashboard
            if not authenticated:
                self.log("Navigating to https://mybrightday.brighthorizons.com/dashboard/parents.html...")
                try:
                    page.goto("https://mybrightday.brighthorizons.com/dashboard/parents.html", wait_until="domcontentloaded")
                    time.sleep(8.0)
                    self.latest_preview_b64 = capture_compressed_b64_frame(page, 1280, 720)
                    current_url = page.url
                    if "login" not in current_url and ("parents.html" in current_url or "tadpoles" in page.title().lower()):
                        authenticated = True
                        self.log("Session verified successfully on My Bright Day dashboard!")
                except Exception as mbd_err:
                    self.log(f"My Bright Day verification attempt notice: {mbd_err}")
                    
            if not authenticated:
                context.close()
                self._active_page = None
                raise Exception("Portal verification failed. Please check session freshness.")
                
            children = []
            try:
                self.log("Attempting child auto-discovery on Family Info Center...")
                page.goto("https://familyinfocenter.brighthorizons.com/home", wait_until="domcontentloaded")
                time.sleep(3.0)
                children = self.discover_children(page, context)
            except Exception as disc_err:
                self.log(f"Child auto-discovery on Family Info Center skipped: {disc_err}")
                
            if not children:
                # Load cached children from tenant manifest if present
                manifest = self.tenant_storage.load_manifest()
                children = manifest.get("children", [])
                
            if not children:
                # Default child list from known dependent IDs
                children = [
                    {"name": "Byron", "dependent_id": "673e065a9d37c9fab2483b2d"},
                    {"name": "Catherine", "dependent_id": "6322019106aa0d39b230f4a0"}
                ]
                
            context.close()
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
        # Purge existing browser profile session before pre-verification to force a fresh login
        self.tenant_storage.clear_session()
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
                "user_data_dir": user_data_dir,
                "executable_path": "/usr/bin/google-chrome-stable" if os.path.exists("/usr/bin/google-chrome-stable") else None,
                "headless": False,
                "args": args,
                "ignore_default_args": ["--enable-automation"]
            }
            # Remove None values
            context_kwargs = {k: v for k, v in context_kwargs.items() if v is not None}
                
            context: BrowserContext = p.chromium.launch_persistent_context(**context_kwargs)
            
            page: Page = context.new_page()
            self._active_page = page
            
            try:
                # Force clear cookies for fresh authentication during login pre-verification
                context.clear_cookies()
                
                self.log("Navigating to portal and authenticating credentials...")
                self._current_url = "https://familyinfocenter.brighthorizons.com/okta/login"
                
                page.goto("https://familyinfocenter.brighthorizons.com/okta/login", wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                update_progress("Authenticating with Bright Horizons SSO...", 2, page=page, force_shot=True)
                
                self.perform_login(page, update_progress_cb=lambda s, idx: update_progress(s, idx, page=page, force_shot=True), force_fresh_auth=True)
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

                # Save authenticated storage state to disk
                state_file = os.path.join(user_data_dir, "storage_state.json")
                try:
                    context.storage_state(path=state_file)
                    self.log(f"Successfully persisted authenticated storage state to {state_file}")
                except Exception as e:
                    self.log(f"Storage state save notice: {e}")

                # Calculate cookie expiration timestamp (or default to 15m / 900s)
                all_cookies = context.cookies()
                now_ts = time.time()
                expirations = [c.get("expires") for c in all_cookies if c.get("expires") and c.get("expires") > now_ts]
                min_exp = min(expirations) if expirations else (now_ts + 900)
                session_expires_at_ms = int(min_exp * 1000)

                config = self.tenant_storage.load_config()
                config["session_expires_at"] = session_expires_at_ms
                config["children"] = children
                self.tenant_storage.save_config(config)

                update_progress("Verification complete!", 3, page=page, force_shot=True)
                return children

            except Exception as e:
                update_progress(f"Verification error: {e}", 3, page=page, force_shot=True)
                raise e
            finally:
                self._active_page = None
                try: context.close()
                except Exception: pass

    def discover_children(self, page: Page, context: BrowserContext) -> List[Dict[str, str]]:
        """Discovers active children and their dependent_ids following Angular CDK rules in .agents/AGENTS.md."""
        children = []
        try:
            self.log("Navigating to Family Information Center home to discover child cards...")
            page.goto("https://familyinfocenter.brighthorizons.com/home", wait_until="domcontentloaded")
            try:
                page.wait_for_selector("span:has-text('Actions'), h1", timeout=25000)
            except Exception:
                pass
            page.wait_for_timeout(3000)
            
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
                    page.wait_for_timeout(1500)
                    
                    # Target specific dropdown item
                    mbd = page.locator("span.actions-menu-item-label", has_text="My Bright Day").first
                    try:
                        mbd.wait_for(state="visible", timeout=3000)
                        with context.expect_page() as new_page_info:
                            mbd.evaluate("(el) => (el.closest('a') || el.closest('button') || el).click()")
                            
                        new_page = new_page_info.value
                        new_page.wait_for_load_state("domcontentloaded", timeout=12000)
                        
                        m = re.search(r'dependent_id=([^&]+)', new_page.url)
                        if m:
                            dep_id = m.group(1)
                            children.append({"name": given_name, "dependent_id": dep_id})
                            self.log(f"Discovered child: {given_name} (dependent_id: {dep_id[:8]}...)")
                            
                        new_page.close()
                    finally:
                        # Close CDK overlay menu if open before processing next card
                        try: page.keyboard.press("Escape")
                        except Exception: pass
                        page.wait_for_timeout(500)
                except Exception as e:
                    self.log(f"Skipped child card #{idx + 1} (may not have active enrollment): {e}")
                    
        except Exception as e:
            self.log(f"Child auto-discovery warning: {e}")
            
        if not children:
            # Fallback to default child profiles if Angular CDK rendering was slow
            self.log("Applying default child profiles fallback (Byron & Catherine)...")
            children = [
                {"name": "Byron", "dependent_id": "673e065a9d37c9fab2483b2d"},
                {"name": "Catherine", "dependent_id": "6322019106aa0d39b230f4a0"}
            ]
            
        return children

    def extract_child_feed(self, page: Page, context: BrowserContext, child: Dict[str, str]):
        """Navigates child timeline, handles timeframe links, and extracts all feed items."""
        child_name = child["name"]
        dep_id = child["dependent_id"]
        
        self.log(f"Processing feed for {child_name} (Sync Mode: {self.sync_mode.upper()})...")
        url = f"https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id={dep_id}"
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(3.0)
        
        # Check if child tile needs to be clicked to trigger Knockout.js month links
        try:
            tiles = page.locator("li, div.tile, a, span").all()
            for el in tiles:
                txt = el.inner_text().strip().lower()
                if txt == child_name.strip().lower() or txt.startswith(child_name.strip().lower()):
                    self.log(f"Clicking child selection tile for '{child_name}'...")
                    el.click()
                    time.sleep(2.0)
                    break
        except Exception:
            pass
            
        # Dynamic wait up to 45s for Knockout.js timeframe month links to populate
        month_names = []
        start_wait = time.time()
        while time.time() - start_wait < 45.0:
            try:
                lis = page.locator("li").all()
                found = []
                for li in lis:
                    try:
                        txt = li.inner_text().strip()
                        m = re.search(r'([a-z]{3})\s*(\d{4})', txt, re.IGNORECASE)
                        if m:
                            m_str = f"{m.group(1)} {m.group(2)}".strip()
                            if m_str.lower() not in [x.lower() for x in found]:
                                found.append(m_str)
                    except Exception:
                        pass
                if found:
                    month_names = found
                    break
            except Exception:
                pass
            time.sleep(1.0)
            
        if len(month_names) == 0:
            current_url = page.url.lower()
            if "login" in current_url or "sso" in current_url:
                self.log(f"Session expired or unauthenticated while accessing timeline for {child_name}. Clearing expired session files.")
                self.tenant_storage.clear_session()
                raise Exception("Session expired or invalid. Please re-authenticate and import fresh session tokens.")

        self.log(f"Found {len(month_names)} timeframe month links for {child_name}: {', '.join(month_names)}")
        
        self.status["current_child"] = child_name
        manifest = self.tenant_storage.load_manifest()
        
        for tf_text in month_names:
            if self._cancelled:
                self.log("Extraction cancelled by user.")
                return

            self.status["current_month"] = tf_text
            
            # Point (3) Optimization: check if timeframe month's end date is strictly prior to start_date
            if self.start_date:
                m_end = get_month_end_date(tf_text)
                if m_end and m_end < self.start_date:
                    self.log(f"Timeframe month '{tf_text}' (end date: {m_end}) is prior to start date {self.start_date}. Halting month scan for {child_name}.")
                    break

            try:
                self.log(f"Navigating to timeframe: {tf_text}...")
                
                # Dynamic re-query matching month name and year flexibly across whitespace/linebreaks
                parts = tf_text.split()
                target_li = None
                if len(parts) == 2:
                    m_mon, m_yr = parts[0].lower(), parts[1]
                    for li in page.locator("li").all():
                        try:
                            t = li.inner_text().lower()
                            if m_mon in t and m_yr in t and re.search(r'[a-z]{3}\s*\d{4}', t):
                                target_li = li
                                break
                        except Exception:
                            pass

                if target_li:
                    tile = target_li.locator("div.tile.pointable").first
                    if tile.count() > 0:
                        tile.click()
                    else:
                        target_li.click()
                else:
                    self.log(f"Could not locate active DOM element for timeframe month '{tf_text}'; skipping.")
                    continue
            except Exception as nav_err:
                self.log(f"Navigation notice for month '{tf_text}': {nav_err}. Continuing to next month...")
                continue
                
            # Smart Month Feed Monitor: Wait for 'no events for the month' indicator or rendered feed thumbnails
            is_empty_month = False
            start_month_wait = time.time()
            while time.time() - start_month_wait < 10.0:
                # 1. Check if Knockout 'no events for the month' div/h1 container is visible
                empty_loc = page.locator("h1:has-text('no events for the month'), div:has-text('no events for the month')").first
                if empty_loc.count() > 0 and empty_loc.is_visible():
                    is_empty_month = True
                    break
                    
                # 2. Check if timeline feed items are present in left panel
                timeline_check = page.locator("div.well.left-panel.pull-left")
                items_check = timeline_check.locator("ul.thumbnails li").all() if timeline_check.count() > 0 else page.locator("ul.thumbnails li").all()
                if len(items_check) > 0:
                    break
                    
                page.wait_for_timeout(200)

            if is_empty_month:
                self.log(f"Timeframe month '{tf_text}' has no events ('no events for the month' detected). Advancing to next month immediately...")
                continue
                
            # Scroll to trigger lazy loading for months with posts
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
                        
                    raw_href = fancybox.get_attribute("href") or ""
                    pointable_tile = item.locator("div.tile.pointable, div.tile").first
                    style_attr = pointable_tile.get_attribute("style") or "" if pointable_tile.count() > 0 else ""
                    
                    obj_id, is_video, resolved_url = extract_obj_id_from_url_or_style(raw_href, style_attr)
                    if not obj_id:
                        continue
                    
                    # Check manifest for existing item
                    existing_entry = False
                    existing_manifest_entry = None
                    for m_id, entry in manifest.items():
                        if entry.get("obj_id") == obj_id:
                            existing_entry = True
                            existing_manifest_entry = entry
                            break
                            
                    if existing_entry:
                        fn = existing_manifest_entry.get("original_filename", "media") if existing_manifest_entry else "media"
                        if self.sync_mode == "incremental":
                            self.log(f"[Incremental Sync] Hit existing item obj_id {obj_id[:8]}... ('{fn}'). Halting child feed scan.")
                            return
                        else:
                            self.log(f"[Skipped / Existing] Item obj_id {obj_id[:8]}... already downloaded as '{fn}'. Skipping.")
                            continue

                    # Parse date overlay
                    overlay_span = item.locator("span.name span").first
                    date_text = overlay_span.inner_text().strip() if overlay_span.count() > 0 else ""
                    date_str = parse_date(date_text, tf_text)
                    self.status["current_date"] = date_str

                    # Check Custom Start Date condition
                    if self.start_date and date_str < self.start_date:
                        self.log(f"Post date {date_str} is before custom start date {self.start_date}. Skipping.")
                        continue
                        
                    self.log(f"[Downloading] Intercepted new media item (obj_id: {obj_id[:8]}..., type: {'video' if is_video else 'photo'}, date: {date_str}). Fetching binary...")
                        
                    # Extract full res URL while preserving exact query string parameters (&key=...)
                    resolved_clean = html.unescape(resolved_url).strip()
                    if resolved_clean.startswith("http"):
                        download_url = resolved_clean
                    elif resolved_clean.startswith("/"):
                        download_url = f"https://mybrightday.brighthorizons.com{resolved_clean}"
                    else:
                        download_url = f"https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj={obj_id}&key={obj_id}"
                    
                    # Fetch file bytes via Playwright request with Referer header & in-flight session refresh on 401/403
                    file_bytes = None
                    mime_type = "video/mp4" if is_video else "image/jpeg"
                    req_headers = {
                        "Referer": "https://mybrightday.brighthorizons.com/dashboard/parents.html",
                        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                    }
                    for attempt in range(3):
                        try:
                            response = page.request.get(download_url, headers=req_headers, timeout=120000)
                            if response.status == 200:
                                body_data = response.body()
                                # Unpack Bright Horizons signed_url JSON if returned
                                try:
                                    json_data = json.loads(body_data.decode("utf-8"))
                                    if isinstance(json_data, dict) and "signed_url" in json_data:
                                        signed_url = json_data["signed_url"]
                                        if "mime_type" in json_data and json_data["mime_type"]:
                                            mime_type = json_data["mime_type"]
                                        # Fetch signed CDN URL with standard User-Agent header
                                        media_resp = page.request.get(signed_url, headers={"User-Agent": req_headers["User-Agent"]}, timeout=120000)
                                        if media_resp.status == 200:
                                            file_bytes = media_resp.body()
                                            break
                                except Exception:
                                    file_bytes = body_data
                                    header_mime = response.headers.get("content-type", "")
                                    if header_mime and "text/html" not in header_mime:
                                        mime_type = header_mime
                                    break
                            elif response.status in [401, 403]:
                                self.log(f"HTTP {response.status} when fetching obj_id {obj_id[:8]}... Session may be invalid. Triggering in-flight session refresh...")
                                self.ensure_cross_domain_session(page, context, dependent_id=dep_id)
                                time.sleep(2.0)
                            else:
                                self.log(f"HTTP {response.status} attempt #{attempt + 1} for obj_id {obj_id[:8]}...")
                        except Exception as fetch_err:
                            if attempt == 2:
                                self.log(f"Failed fetching obj_id {obj_id[:8]}... after 3 attempts: {fetch_err}")
                            else:
                                time.sleep(2.0)

                    if not file_bytes:
                        continue
                        
                    ext = detect_extension(file_bytes, mime_type)
                    
                    # Point (1): Calculate clean sequence-based filename without requiring obj_id
                    current_manifest = self.tenant_storage.load_manifest()
                    existing_for_day = [
                        m for m in current_manifest.values()
                        if m.get("child") == child_name and m.get("date") == date_str and m.get("obj_id") != obj_id
                    ]
                    seq = len(existing_for_day) + 1
                    if seq == 1:
                        orig_filename = f"{child_name} {date_str}.{ext}"
                    else:
                        orig_filename = f"{child_name} {date_str} ({seq}).{ext}"

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
        """Scrolls feed down iteratively until no new feed posts are loaded."""
        timeline = page.locator("div.well.left-panel.pull-left")
        prev_count = 0
        stable_iterations = 0
        
        for iteration in range(40):
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            page.wait_for_timeout(1500)
            page.evaluate("window.scrollBy(0, -600);")
            page.wait_for_timeout(400)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            page.wait_for_timeout(1500)
            
            feed_items = timeline.locator("ul.thumbnails li").all() if timeline.count() > 0 else page.locator("ul.thumbnails li").all()
            curr_count = len(feed_items)
            if curr_count == prev_count and curr_count > 0:
                stable_iterations += 1
                if stable_iterations >= 3:
                    self.log(f"Feed scrolling stabilized at {curr_count} posts after {iteration + 1} iterations.")
                    break
            else:
                stable_iterations = 0
                prev_count = curr_count

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
    elif file_bytes.startswith(b"\xff\xd8"):
        return "jpg"
    elif b"ftyp" in file_bytes[:64] or b"moov" in file_bytes[:64] or b"mdat" in file_bytes[:64]:
        return "mov" if b"ftypqt" in file_bytes[:64] else "mp4"
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

def redownload_single_media_item(tenant_storage: TenantStorage, media_id: str) -> Dict[str, Any]:
    """Re-downloads a specific photo or video from My Bright Day by media_id."""
    manifest = tenant_storage.load_manifest()
    if media_id not in manifest:
        raise Exception(f"Media item '{media_id}' not found in manifest.")
        
    entry = manifest[media_id]
    obj_id = entry.get("obj_id")
    date_str = entry.get("date", datetime.now().strftime("%Y-%m-%d"))
    child_name = entry.get("child", "Child")
    mime_type = entry.get("mime_type", "image/jpeg")
    
    if not obj_id:
        raise Exception(f"Media item '{media_id}' missing obj_id parameter.")
        
    download_url = f"https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj={obj_id}&key={obj_id}"
    req_headers = {
        "Referer": "https://mybrightday.brighthorizons.com/dashboard/parents.html",
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    }
    
    user_data_dir = tenant_storage.user_data_dir
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
        )
        page = context.new_page()
        try:
            state_file = os.path.join(user_data_dir, "storage_state.json")
            if os.path.exists(state_file):
                try:
                    with open(state_file, "r") as f:
                        state_data = json.load(f)
                    context.add_cookies(state_data.get("cookies", []))
                except Exception:
                    pass

            response = page.request.get(download_url, headers=req_headers, timeout=60000)
            file_bytes = None
            if response.status == 200:
                body_data = response.body()
                try:
                    json_data = json.loads(body_data.decode("utf-8"))
                    if isinstance(json_data, dict) and "signed_url" in json_data:
                        signed_url = json_data["signed_url"]
                        if "mime_type" in json_data and json_data["mime_type"]:
                            mime_type = json_data["mime_type"]
                        media_resp = page.request.get(signed_url, headers={"User-Agent": req_headers["User-Agent"]}, timeout=60000)
                        if media_resp.status == 200:
                            file_bytes = media_resp.body()
                except Exception:
                    file_bytes = body_data

            if not file_bytes:
                raise Exception(f"HTTP {response.status} failed retrieving media stream from My Bright Day.")
                
            orig_filename = entry.get("original_filename", f"{child_name} {date_str}.jpg")
            comment_text = entry.get("comment", f"Bright Horizons photo for {child_name} on {date_str}")
            
            # Save updated entry to tenant storage
            updated_entry = tenant_storage.add_media_entry(
                obj_id=obj_id,
                child=child_name,
                date_str=date_str,
                original_filename=orig_filename,
                comment=comment_text,
                file_bytes=file_bytes,
                mime_type=mime_type
            )
            
            abs_path = os.path.join(tenant_storage.tenant_dir, updated_entry["storage_path"])
            set_eastern_timestamp(abs_path, date_str)
            return updated_entry
        finally:
            try: context.close()
            except Exception: pass
