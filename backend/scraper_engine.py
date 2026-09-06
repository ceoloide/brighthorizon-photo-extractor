# SPDX-License-Identifier: MIT
# Headless Scraper Engine for Bright Horizons Photo Extractor
import io
import json
import os
import re
import sys
import time
import requests
import struct
import threading
from PIL import Image
import zlib
from datetime import datetime, timedelta
from typing import Dict, Any, List, Callable, Optional, Tuple
import html
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright, BrowserContext, Page
import hashlib
from urllib.parse import urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed
from backend.database import TenantStorage
from backend.dom_parser import (
    extract_obj_id_from_url_or_style,
    get_month_end_date,
    wait_for_month_feed_ready,
    extract_feed_items,
)

try:
    from playwright_stealth import stealth_sync
except ImportError:
    stealth_sync = None

FLARESOLVERR_URL = os.environ.get("FLARESOLVERR_URL", "http://192.168.1.176:8191/v1")

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
def check_and_refetch_asset(
    file_bytes: bytes,
    o_id: str,
    k_id: str,
    req_headers: dict,
    session_cookies: dict,
    is_vid: bool,
    max_retries: int = 2,
    log_func: Optional[Callable[[str], None]] = None
) -> Tuple[bytes, bool]:
    """
    Checks if downloaded media payload is sub-optimal:
    - Photo (`is_vid=False`): checks if payload is 200x200px thumbnail.
    - Video (`is_vid=True`): checks if payload fell back to JPEG image format.

    If sub-optimal, attempts up to `max_retries` fresh signed URL queries to obtain
    a full-resolution image (> 200x200) or true MP4 video stream.

    Returns:
        Tuple of (final_file_bytes, upgraded_flag)
    """
    if not file_bytes:
        return file_bytes, False

    def _is_200x200_photo(b: bytes) -> bool:
        try:
            with Image.open(io.BytesIO(b)) as img:
                return img.width == 200 and img.height == 200
        except Exception:
            return False

    def _is_video_jpeg_fallback(b: bytes) -> bool:
        if b.startswith(b"\xff\xd8"):
            return True
        try:
            with Image.open(io.BytesIO(b)):
                return True
        except Exception:
            return False

    needs_refetch = False
    refetch_reason = ""

    if is_vid:
        if _is_video_jpeg_fallback(file_bytes):
            needs_refetch = True
            refetch_reason = "Video payload fell back to JPEG image thumbnail"
    else:
        if _is_200x200_photo(file_bytes):
            needs_refetch = True
            refetch_reason = "Photo downloaded as 200x200px thumbnail"

    if not needs_refetch:
        return file_bytes, False

    fallback_url = f"https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj={o_id}&key={k_id}"
    if log_func:
        log_func(f"[{'Video' if is_vid else 'Photo'} Remediation Warning] {refetch_reason} for obj_id {o_id[:8]}. Attempting signed URL refetch (up to {max_retries} retries)...")

    current_bytes = file_bytes
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.get(fallback_url, headers=req_headers, cookies=session_cookies, timeout=60)
            if resp.status_code == 200:
                fetched_bytes = None
                try:
                    json_data = json.loads(resp.content.decode("utf-8"))
                    if isinstance(json_data, dict) and "signed_url" in json_data:
                        s_url = json_data["signed_url"]
                        s_resp = requests.get(s_url, headers={"User-Agent": req_headers.get("User-Agent", "")}, timeout=60)
                        if s_resp.status_code == 200:
                            fetched_bytes = s_resp.content
                except Exception:
                    fetched_bytes = resp.content

                if fetched_bytes:
                    if is_vid:
                        if not _is_video_jpeg_fallback(fetched_bytes):
                            if log_func:
                                log_func(f"[Video Stream Upgrade Success] Successfully retrieved full video stream ({len(fetched_bytes)} bytes) for obj_id {o_id[:8]} on attempt {attempt}/{max_retries}.")
                            return fetched_bytes, True
                    else:
                        if not _is_200x200_photo(fetched_bytes):
                            w, h = "unknown", "unknown"
                            try:
                                with Image.open(io.BytesIO(fetched_bytes)) as new_img:
                                    w, h = new_img.width, new_img.height
                            except Exception:
                                pass
                            if log_func:
                                log_func(f"[Resolution Upgrade Success] Successfully retrieved full-resolution image ({w}x{h}px) for obj_id {o_id[:8]} on attempt {attempt}/{max_retries}.")
                            return fetched_bytes, True

        except Exception as err:
            if log_func:
                log_func(f"[Refetch Retry #{attempt}/{max_retries}] Refetch error for obj_id {o_id[:8]}: {err}")
        time.sleep(1.0)

    if log_func:
        log_func(f"[Remediation Notice] Asset obj_id {o_id[:8]} remains un-upgraded after {max_retries} retries; retaining existing payload.")

    return current_bytes, False

check_and_refetch_if_200x200 = check_and_refetch_asset

import shutil

def clean_user_data_locks(user_data_dir: str):
    """Safely removes stale Chromium Singleton lock files and ensures write permissions across user_data_dir."""
    if not os.path.exists(user_data_dir):
        return
    try:
        os.chmod(user_data_dir, 0o777)
    except Exception:
        pass

    for root, dirs, files in os.walk(user_data_dir):
        try:
            os.chmod(root, 0o777)
        except Exception:
            pass

        for fname in files:
            if "Singleton" in fname or fname == "RunningChromeVersion" or "Lock" in fname:
                fpath = os.path.join(root, fname)
                try:
                    if os.path.islink(fpath):
                        os.unlink(fpath)
                    elif os.path.exists(fpath):
                        os.remove(fpath)
                except Exception:
                    pass

        for dname in dirs:
            if "Singleton" in dname:
                dpath = os.path.join(root, dname)
                try:
                    shutil.rmtree(dpath, ignore_errors=True)
                except Exception:
                    pass

def launch_stealth_persistent_context(playwright_instance, user_data_dir: str, extra_args: list = None, **kwargs):
    """Launches a persistent browser context targeting real system Chrome with anti-bot masking flags."""
    clean_user_data_locks(user_data_dir)
    ensure_xvfb_display(1280, 720)

    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
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

            self.job.log_structured(
                level="DEBUG",
                category="NETWORK_RESP",
                message=f"<-- HTTP {status} {url}",
                details=details
            )

    def _on_request_failed(self, request):
        url = request.url
        if any(domain in url for domain in ["brighthorizons", "auth0", "cloudflare", "obj_attachment"]):
            failure = request.failure
            self.job.log_structured(
                level="DEBUG",
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
        self.tenant_storage.clear_log()
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
        """Structured logging method storing log messages, appending to persistent disk log, and calling log_callback."""
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        level_norm = level.upper()

        # Force all Network activity (requests, responses, failures, warnings) to DEBUG level
        if category.startswith("NETWORK"):
            level_norm = "DEBUG"

        entry_str = f"[{timestamp}] [{level_norm}] [{category}] {message}"
        
        # Persistent disk log receives all logs (including DEBUG network requests)
        self.tenant_storage.append_log(entry_str)

        # UI console logs (self.status["logs"]) receive INFO, WARN, and ERROR engine logs,
        # but filter out DEBUG network logs so network traffic is not surfaced on the UI
        if level_norm != "DEBUG":
            self.status["logs"].append(entry_str)
            if len(self.status["logs"]) > 5000:
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
                    from backend.dom_parser import dismiss_cdk_overlays
                    actions_spans = page.locator("span", has_text="Actions").all()
                    for span in actions_spans:
                        try:
                            span.click(timeout=3000)
                            time.sleep(1.0)
                            mbd = page.locator("span.actions-menu-item-label", has_text="My Bright Day").first
                            if mbd.count() > 0 and mbd.is_visible():
                                with context.expect_page() as new_page_info:
                                    mbd.evaluate("(el) => (el.closest('a') || el.closest('button') || el).click()")
                                mbd_page = new_page_info.value
                                mbd_page.wait_for_load_state("domcontentloaded")
                                page = mbd_page
                                self._active_page = page
                                time.sleep(5.0)
                                self.log(f"Successfully landed on My Bright Day via SSO: {page.url}")
                                break
                            else:
                                dismiss_cdk_overlays(page)
                        except Exception as e:
                            self.log(f"Actions click attempt note: {e}")
                            dismiss_cdk_overlays(page)

                    # Fallback: if children are unenrolled and no "My Bright Day" was found
                    if "parents.html" not in page.url and "familyinfocenter" in page.url:
                        dismiss_cdk_overlays(page)
                        self.log("No active 'My Bright Day' link found in Actions menu (children may be unenrolled). Executing automated SSO token exchange...")
                        from backend.dom_parser import exchange_mbd_jwt_token
                        sso_ok = exchange_mbd_jwt_token(page, logger=self.log)
                        if sso_ok:
                            try:
                                context.storage_state(path=state_file)
                                self.log("Persisted fresh SSO session cookies to storage_state.json")
                            except Exception as ss_err:
                                self.log(f"Notice persisting storage_state: {ss_err}")
                        else:
                            self.log("SSO token exchange note: attempting direct navigation fallback...")
                            try:
                                page.goto("https://mybrightday.brighthorizons.com/dashboard/parents.html", wait_until="domcontentloaded")
                                time.sleep(4.0)
                            except Exception as nav_err:
                                self.log(f"Direct navigation notice: {nav_err}")
                        self.log(f"Portal handoff landed on: {page.url}")

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
                    self.log("Enrolled children list is empty; executing automatic child rediscovery step...")
                    try:
                        rediscovered = self.discover_children(page, context)
                        if rediscovered:
                            all_children = rediscovered
                            config["children"] = all_children
                            self.tenant_storage.save_config(config)
                            self.log(f"Child rediscovery successful! Found and saved {len(all_children)} profile(s): {[c['name'] for c in all_children]}")
                        else:
                            self.log("Child rediscovery step completed with 0 profiles found; extracting timeline feed directly.")
                    except Exception as disc_err:
                        self.log(f"Child rediscovery step notice: {disc_err}")

                children_to_process = all_children if all_children else [{"name": "Timeline", "dependent_id": "all"}]

                if self.target_child != "all":
                    target_clean = self.target_child.strip().lower()
                    matching = [c for c in children_to_process if c.get("name", "").strip().lower() == target_clean or c.get("name", "").strip().lower().startswith(target_clean)]
                    if matching:
                        children = matching
                        centers_desc = ", ".join(c.get("location_name", "Center") for c in matching if c.get("location_name"))
                        self.log(f"Target child '{matching[0]['name']}' selected ({len(matching)} center profile(s): {centers_desc or 'Default'}). Processing all center feeds.")
                    elif not all_children or (len(all_children) == 1 and all_children[0].get("name") == "Timeline"):
                        self.log(f"Target child '{self.target_child}' specified for account with 0 active center profiles. Processing direct timeline feed.")
                        children = [{"name": self.target_child, "dependent_id": "all"}]
                    else:
                        raise Exception(f"Selected target child '{self.target_child}' was not found among enrolled children: {[c.get('name') for c in all_children]}")
                else:
                    children = children_to_process

                # Step 3: Extract feed for children
                self.status["current_step"] = "Extracting photos & videos"
                for child in children:
                    if self._cancelled: break
                    self.extract_child_feed(page, context, child)
                    
                if self._cancelled:
                    self.status["state"] = "cancelled"
                    self.status["current_step"] = "Extraction cancelled"
                else:
                    # Stage 2: Post-Extraction Thumbnail Sweep (re-download 200x200 images 1 time)
                    if self.status.get("files_downloaded", 0) > 0:
                        self._run_post_extraction_thumbnail_sweep(state_file)
                    else:
                        self.log("Skipping post-extraction thumbnail sweep (0 files downloaded in this extraction run).")

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

    def _run_post_extraction_thumbnail_sweep(self, state_file: Optional[str] = None):
        """
        Stage 2 Job Sweep: Scans tenant manifest for any media assets that remain
        200x200px on disk, and executes a 1-time re-download pass.
        """
        self.log("Starting final post-extraction sweep for 200x200 thumbnails...")
        manifest = self.tenant_storage.load_manifest()
        if not manifest:
            return

        session_cookies = {}
        if state_file and os.path.exists(state_file):
            try:
                with open(state_file, "r", encoding="utf-8") as sf:
                    st = json.load(sf)
                    session_cookies = {c["name"]: c["value"] for c in st.get("cookies", [])}
            except Exception:
                pass

        req_headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
            "Referer": "https://mybrightday.brighthorizons.com/dashboard/parents.html"
        }

        items_scanned = 0
        thumbnails_found = 0
        upgraded_count = 0

        for media_id, item in manifest.items():
            if self._cancelled:
                break

            s_path = item.get("storage_path")
            mime_type = item.get("mime_type", "")
            if not s_path or s_path.endswith("_thumb.dat") or mime_type.startswith("video"):
                continue

            abs_path = os.path.join(self.tenant_storage.tenant_dir, s_path)
            if not os.path.exists(abs_path):
                continue

            items_scanned += 1
            file_bytes = None
            try:
                with open(abs_path, "rb") as f:
                    file_bytes = f.read()
            except Exception:
                continue

            if not file_bytes:
                continue

            is_200 = False
            try:
                with Image.open(io.BytesIO(file_bytes)) as img:
                    is_200 = (img.width == 200 and img.height == 200)
            except Exception:
                pass

            if not is_200:
                continue

            thumbnails_found += 1
            obj_id = item.get("obj_id") or media_id
            filename = item.get("original_filename") or os.path.basename(s_path)
            self.log(f"[Post-Extraction Sweep] Identified 200x200 thumbnail for '{filename}' ({media_id[:8]}). Executing 1-time re-download pass...")

            new_bytes, upgraded = check_and_refetch_if_200x200(
                file_bytes=file_bytes,
                o_id=obj_id,
                k_id=obj_id,
                req_headers=req_headers,
                session_cookies=session_cookies,
                is_vid=False,
                max_retries=1,
                log_func=self.log
            )

            if upgraded and new_bytes:
                upgraded_count += 1
                try:
                    self.tenant_storage.add_media_entry(
                        obj_id=obj_id,
                        child=item.get("child", "Child"),
                        date_str=item.get("date", datetime.now().strftime("%Y-%m-%d")),
                        original_filename=filename,
                        comment=item.get("comment", ""),
                        file_bytes=new_bytes,
                        mime_type=mime_type
                    )
                    set_eastern_timestamp(abs_path, item.get("date", datetime.now().strftime("%Y-%m-%d")))
                except Exception as save_err:
                    self.log(f"[Post-Extraction Sweep Notice] Error updating asset for '{filename}': {save_err}")

        self.log(f"[Post-Extraction Sweep Complete] Scanned {items_scanned} images; identified {thumbnails_found} 200x200 thumbnails; upgraded {upgraded_count} assets to full resolution.")

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
            from backend.dom_parser import dismiss_cdk_overlays
            actions_spans = page.locator("span", has_text="Actions").all()
            for span in actions_spans:
                try:
                    span.click(timeout=3000)
                    page.wait_for_timeout(1000)
                    mbd = page.locator("span.actions-menu-item-label", has_text="My Bright Day").first
                    if mbd.count() > 0 and mbd.is_visible():
                        with context.expect_page() as new_page_info:
                            mbd.evaluate("(el) => (el.closest('a') || el.closest('button') || el).click()")
                        mbd_page = new_page_info.value
                        mbd_page.wait_for_load_state("domcontentloaded")
                        mbd_page.wait_for_timeout(3000)
                        handshake_success = True
                        mbd_page.close()
                        break
                    else:
                        dismiss_cdk_overlays(page)
                except Exception as e:
                    self.log(f"SSO handshake click notice: {e}")
                    dismiss_cdk_overlays(page)
        except Exception as e:
            self.log(f"SSO handshake locator notice: {e}")

        if not handshake_success:
            # Fallback: Execute automated SSO JWT token exchange
            try:
                from backend.dom_parser import dismiss_cdk_overlays, exchange_mbd_jwt_token
                dismiss_cdk_overlays(page)
                self.log("Actions menu handshake unavailable; executing automated SSO JWT token exchange...")
                handshake_success = exchange_mbd_jwt_token(page, dependent_id=dependent_id, logger=self.log)
                if not handshake_success:
                    target_mbd = f"https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id={dependent_id}" if dependent_id else "https://mybrightday.brighthorizons.com/dashboard/parents.html"
                    self.log(f"SSO exchange note: navigating directly to {target_mbd}...")
                    page.goto(target_mbd, wait_until="domcontentloaded")
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
            if btn.count() > 0:
                try:
                    btn.click(timeout=3000, force=True)
                except Exception as click_err:
                    self.log(f"Notice during native click on Log In button: {click_err}. Trying JS click fallback...")
                    try:
                        btn.evaluate("(el) => (el.closest('a') || el.closest('button') || el).click()")
                    except Exception:
                        pass
            try:
                page.wait_for_load_state("domcontentloaded", timeout=6000)
            except Exception:
                pass
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
                    page.wait_for_timeout(400)
                    
                    # If password field is not yet visible, submit username step
                    pwd_inp_check = page.locator("input[name='password']:not(.hide), input[id='password']").first
                    if pwd_inp_check.count() == 0 or not pwd_inp_check.is_visible():
                        self.log("Submitting email step...")
                        btn = page.locator("button[data-action-button-primary='true']:not([aria-hidden='true']), button._button-login-id:not([aria-hidden='true']), button[type='submit']:not([aria-hidden='true']):not([tabindex='-1']):not(.ulp-hidden-form-submit-button), button[name='action']:not([aria-hidden='true']):not([tabindex='-1']), button:has-text('Continue'):not([aria-hidden='true']):not([tabindex='-1']), button:has-text('Next'):not([aria-hidden='true']):not([tabindex='-1'])").first
                        if btn.count() > 0 and btn.is_visible():
                            try:
                                btn.click()
                            except Exception:
                                btn.evaluate("(el) => { if (el.form && el.form.requestSubmit) { try { el.form.requestSubmit(); } catch(e) { el.click(); } } else { el.click(); } }")
                        else:
                            username_inp = page.locator("input[name='username'], input[id='username'], input[type='email']").first
                            if username_inp.count() > 0:
                                try: username_inp.press("Enter")
                                except Exception: pass
                        page.wait_for_timeout(500)
                        try:
                            page.locator("input[name='password']:not(.hide), input[id='password'], span#error-element-username, div#error-element-username, .ulp-input-error-message").first.wait_for(state="visible", timeout=15000)
                        except Exception:
                            pass
                        self.check_auth0_errors(page)

            # Step 2: Handle Password Entry
            pwd_inp = page.locator("input[name='password']:not(.hide), input[id='password']").first
            pwd_inp.wait_for(state="visible", timeout=30000)
            
            self.log("Filling password...")
            if update_progress_cb: update_progress_cb("Submitting password...", 2)
            page.fill("input[name='password']:not(.hide), input[id='password']", self.password)
            self.log("Submitting password step...")
            btn_pwd = page.locator("button[data-action-button-primary='true']:not([aria-hidden='true']), button[type='submit']:not([aria-hidden='true']):not([tabindex='-1']):not(.ulp-hidden-form-submit-button), button[name='action']:not([aria-hidden='true']):not([tabindex='-1']), button:has-text('Log In'):not([aria-hidden='true']):not([tabindex='-1']), button:has-text('Continue'):not([aria-hidden='true']):not([tabindex='-1'])").first
            if btn_pwd.count() > 0 and btn_pwd.is_visible():
                try:
                    btn_pwd.click()
                except Exception:
                    btn_pwd.evaluate("(el) => el.click()")
            page.keyboard.press("Enter")
                
            self.log("Waiting for post-login redirection or MFA challenge...")
            try:
                page.wait_for_url(lambda u: "/home" in u or "/dashboard" in u or "/mfa" in u or "familyinfocenter" in u, timeout=45000)
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
                
                submit_mfa_btn = page.locator("button[data-action-button-primary='true']:not([aria-hidden='true']), button[type='submit']:not([aria-hidden='true']):not([tabindex='-1']):not(.ulp-hidden-form-submit-button), button[name='action']:not([aria-hidden='true']):not([tabindex='-1']), button:has-text('Continue'):not([aria-hidden='true']):not([tabindex='-1']), button:has-text('Verify'):not([aria-hidden='true']):not([tabindex='-1'])").first
                if submit_mfa_btn.count() > 0 and submit_mfa_btn.is_visible():
                    submit_mfa_btn.click()
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
                # Load cached children from tenant config or manifest if present
                config = self.tenant_storage.load_config()
                manifest = self.tenant_storage.load_manifest()
                children = config.get("children") or manifest.get("children", [])
                
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
        self.tenant_storage.clear_log()
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
        """
        Discovers enrolled children across all centers.
        First queries /legacy/parents/params for comprehensive multi-center profiles,
        then falls back to Family Info Center Angular DOM discovery if needed,
        and finally to direct My Bright Day navigation and Knockout header DOM discovery.
        """
        try:
            from backend.dom_parser import (
                discover_children_from_parents_params,
                discover_children_from_family_info,
                discover_children_from_mybrightday_dom
            )

            # Fast path 1: query /legacy/parents/params directly
            discovered = discover_children_from_parents_params(page, logger=self.log)
            if discovered:
                self.log(f"Child auto-discovery via My Bright Day API found {len(discovered)} profile(s): {[(c['name'], c.get('location_name', '')) for c in discovered]}")
                return discovered

            # Fast path 2: If on parents.html, check DOM child selector tiles
            if "parents.html" in page.url or "mybrightday" in page.url:
                dom_discovered = discover_children_from_mybrightday_dom(page, logger=self.log)
                if dom_discovered:
                    self.log(f"Child auto-discovery via My Bright Day header DOM found {len(dom_discovered)} profile(s): {[c['name'] for c in dom_discovered]}")
                    return dom_discovered

            # Path 3: Family Info Center Angular discovery
            discovered = discover_children_from_family_info(page, context, logger=self.log)
            if discovered:
                return discovered

            # Path 4: If on familyinfocenter and 0 profiles were found (e.g. unenrolled children),
            # execute automated SSO JWT token exchange to authenticate on My Bright Day before discovering
            if "parents.html" not in page.url:
                self.log("Child auto-discovery on Family Info Center yielded 0 active profiles (children may be unenrolled). Executing SSO token exchange for My Bright Day discovery...")
                try:
                    from backend.dom_parser import exchange_mbd_jwt_token
                    sso_ok = exchange_mbd_jwt_token(page, logger=self.log)
                    if not sso_ok:
                        page.goto("https://mybrightday.brighthorizons.com/dashboard/parents.html", wait_until="domcontentloaded")
                    time.sleep(3.0)
                    discovered = discover_children_from_parents_params(page, logger=self.log)
                    if discovered:
                        self.log(f"Child auto-discovery via My Bright Day API found {len(discovered)} profile(s): {[(c['name'], c.get('location_name', '')) for c in discovered]}")
                        return discovered
                    dom_discovered = discover_children_from_mybrightday_dom(page, logger=self.log)
                    if dom_discovered:
                        self.log(f"Child auto-discovery via My Bright Day header DOM found {len(dom_discovered)} profile(s): {[c['name'] for c in dom_discovered]}")
                        return dom_discovered
                except Exception as mbd_err:
                    self.log(f"Notice during direct My Bright Day discovery: {mbd_err}")

        except Exception as e:
            self.log(f"Child auto-discovery notice: {e}")

        self.log("Child auto-discovery completed: 0 specific child profiles found.")
        return []

    def extract_child_feed(self, page: Page, context: BrowserContext, child: Dict[str, str]):
        """Navigates child timeline, handles timeframe links, and extracts all feed items."""
        child_name = child["name"]
        dep_id = child.get("dependent_id")
        loc_name = child.get("location_name") or ""
        center_tag = f" [{loc_name}]" if loc_name else ""

        self.log(f"Processing feed for {child_name}{center_tag} (ID: {dep_id}) (Sync Mode: {self.sync_mode.upper()})...")
        if dep_id and dep_id != "all":
            url = f"https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id={dep_id}"
        else:
            url = "https://mybrightday.brighthorizons.com/dashboard/parents.html"
        page.goto(url, wait_until="domcontentloaded")
        time.sleep(3.0)

        # Verify active child selection.
        # When navigating with ?dependent_id=..., Knockout.js auto-selects the child matching dependent_id.
        # We do NOT perform blind text matching across the page, which breaks on multi-center
        # accounts or when tiles have profile images (omitting text labels).
        try:
            att_key = child.get("attachment_key")
            page.evaluate("""
                ([depId, attKey]) => {
                    const topUl = document.querySelector('div.pull-right ul.thumbnails') || 
                                  Array.from(document.querySelectorAll('ul.thumbnails')).find(u => !u.closest('div.well'));
                    if (!topUl) return true;

                    const selectedTile = topUl.querySelector('div.tile.selected');
                    if (selectedTile) {
                        if (attKey && selectedTile.getAttribute('data-attachment-key') === attKey) {
                            return true;
                        }
                        return true;
                    }

                    if (attKey) {
                        const matchTile = topUl.querySelector(`div.tile[data-attachment-key="${attKey}"]`);
                        if (matchTile) {
                            matchTile.click();
                            return true;
                        }
                    }
                    return false;
                }
            """, [dep_id, att_key])
        except Exception as sel_err:
            self.log(f"Child selector verification notice: {sel_err}")
            
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
        
        found_previously_downloaded = False
        reached_custom_start_date = False

        for tf_text in month_names:
            if self._cancelled:
                self.log("Extraction cancelled by user.")
                return

            self.status["current_month"] = tf_text
            
            # Start Date Filter Check
            if (self.sync_mode == "custom" or self.start_date) and self.start_date:
                m_end = get_month_end_date(tf_text)
                if m_end and m_end < self.start_date:
                    self.log(f"Timeframe month '{tf_text}' (end date: {m_end}) is prior to custom start date {self.start_date}. Halting month scan for {child_name}.")
                    reached_custom_start_date = True
                    break

            try:
                self.log(f"Navigating to timeframe: {tf_text}...")
                
                # Click timeframe tile targeting inner div.tile
                clicked = page.evaluate("""
                    (text) => {
                        const targetText = text.replace(/\\s+/g, ' ').trim().toLowerCase();
                        const el = Array.from(document.querySelectorAll('li')).find(item => {
                            const cleanItemText = (item.innerText || item.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                            return cleanItemText === targetText;
                        });
                        if (el) {
                            const clickable = el.querySelector('div.tile') || el.querySelector('div') || el;
                            clickable.click();
                            return true;
                        }
                        return false;
                    }
                """, tf_text)

                if not clicked:
                    parts = tf_text.split()
                    if len(parts) == 2:
                        m_mon, m_yr = parts[0].lower(), parts[1]
                        for el in page.locator("li, div.tile.pointable, div.tile").all():
                            try:
                                t = el.inner_text().lower()
                                if m_mon in t and m_yr in t:
                                    el.click()
                                    clicked = True
                                    break
                            except Exception:
                                pass
            except Exception as nav_err:
                self.log(f"Navigation notice for month '{tf_text}': {nav_err}. Continuing to next month...")
                continue

            # Dynamic Wait & Month Feed Readiness Verification
            tf_parts = tf_text.split()
            tf_year = int(tf_parts[1]) if len(tf_parts) == 2 and tf_parts[1].isdigit() else None

            has_feed = False
            max_retries = 2
            for attempt in range(max_retries + 1):
                try:
                    has_feed = wait_for_month_feed_ready(page, tf_text, max_wait_sec=300.0, logger=self.log)
                    break
                except TimeoutError as te:
                    if attempt < max_retries:
                        self.log(f"Timeframe month '{tf_text}' timed out in busy state. Re-clicking tile (attempt {attempt + 1}/{max_retries})...")
                        click_timeframe_tile(page, tf_text)
                    else:
                        self.log(f"Timeframe month '{tf_text}' failed after {max_retries} retries: {te}")
                        has_feed = False

            if not has_feed:
                self.log(f"Skipping empty or unpopulated timeframe month '{tf_text}'.")
                continue

            # Extract Feed Items directly from DOM
            feed_items = extract_feed_items(page, timeframe_year=tf_year, logger=self.log)
            if not feed_items:
                # Fallback to in-browser JS evaluation if locator returned 0 items
                js_items = scrape_photos_and_text(page)
                for ji in js_items:
                    o_id = ji.get("objIdParam") or ji.get("keyId")
                    if not o_id:
                        m_o = re.search(r'obj=([^&]+)', ji.get("src", ""))
                        o_id = m_o.group(1) if m_o else hashlib.md5(ji.get("src", "").encode()).hexdigest()
                    date_str = parse_date(ji.get("dateText", ""), tf_text) or datetime.now().strftime("%Y-%m-%d")
                    feed_items.append({
                        "obj_id": o_id,
                        "media_type": "video" if ji.get("isVideo") else "photo",
                        "is_video": ji.get("isVideo", False),
                        "download_url": ji.get("src", ""),
                        "date_str": date_str,
                        "comment_text": ji.get("commentText", "")
                    })

            self.log(f"Extracted {len(feed_items)} feed items from timeframe {tf_text}.")
            if not feed_items:
                continue

            manifest = self.tenant_storage.load_manifest()

            # Ensure all feed items have date_str resolved
            for item in feed_items:
                if not item.get("date_str"):
                    item["date_str"] = parse_date(item.get("raw_date_text", ""), tf_text) or datetime.now().strftime("%Y-%m-%d")

            # Sort feed items descending by date only for incremental/custom modes
            if self.sync_mode in ("incremental", "custom"):
                feed_items.sort(key=lambda x: x.get("date_str", ""), reverse=True)

            download_queue = []
            seen_in_queue = set()
            max_downloaded_date = None

            if self.sync_mode in ("incremental", "custom"):
                # Step 1: Check for already downloaded pictures
                for item in feed_items:
                    obj_id = item.get("obj_id")
                    if not obj_id:
                        continue
                    is_existing = any(entry.get("obj_id") == obj_id for entry in manifest.values())
                    if is_existing:
                        found_previously_downloaded = True
                        item_date = item.get("date_str")
                        if max_downloaded_date is None or (item_date and item_date > max_downloaded_date):
                            max_downloaded_date = item_date

                # Step 2: Check for reaching custom start date
                if (self.sync_mode == "custom" or self.start_date) and self.start_date:
                    for item in feed_items:
                        item_date = item.get("date_str")
                        if item_date and item_date < self.start_date:
                            reached_custom_start_date = True
                            break

                # Step 3: Remove already downloaded items, all that are older than max_downloaded_date,
                # and all that are older than custom start date
                for item in feed_items:
                    if self._cancelled:
                        self.log("Extraction cancelled by user.")
                        return

                    obj_id = item.get("obj_id")
                    if not obj_id:
                        continue

                    item_date = item.get("date_str")

                    # Remove if older than custom start date
                    if (self.sync_mode == "custom" or self.start_date) and self.start_date and item_date and item_date < self.start_date:
                        self.log(f"[Cutoff / Start Date] Item {obj_id[:8]} ({item_date}) is prior to custom start date {self.start_date}. Excluding.")
                        continue

                    # Remove if already downloaded
                    is_existing = any(entry.get("obj_id") == obj_id for entry in manifest.values())
                    if is_existing:
                        self.log(f"[Cutoff / Previously Downloaded] Item {obj_id[:8]} ({item_date}) already in manifest. Excluding.")
                        continue

                    # Remove if older than the newest downloaded item in this timeframe
                    if max_downloaded_date and item_date and item_date < max_downloaded_date:
                        self.log(f"[Cutoff / Older Than Downloaded] Item {obj_id[:8]} ({item_date}) is older than downloaded cutoff ({max_downloaded_date}). Excluding.")
                        continue

                    if obj_id in seen_in_queue:
                        continue
                    seen_in_queue.add(obj_id)

                    download_queue.append({
                        "obj_id": obj_id,
                        "is_video": item.get("is_video", False),
                        "download_url": item.get("download_url"),
                        "date_str": item_date,
                        "comment": item.get("comment_text", "")
                    })
            else:
                # Full mode: only deduplicate existing items without pruning older items
                for item in feed_items:
                    if self._cancelled:
                        self.log("Extraction cancelled by user.")
                        return

                    obj_id = item.get("obj_id")
                    if not obj_id:
                        continue

                    item_date = item.get("date_str")
                    if self.start_date and item_date and item_date < self.start_date:
                        self.log(f"[Start Date Filter] Item {obj_id[:8]} ({item_date}) is prior to custom start date {self.start_date}. Skipping.")
                        continue

                    is_existing = any(entry.get("obj_id") == obj_id for entry in manifest.values())
                    if is_existing:
                        self.log(f"[Skipped / Existing] Item obj_id {obj_id[:8]} ({item_date}) already downloaded. Skipping.")
                        continue

                    if obj_id in seen_in_queue:
                        continue
                    seen_in_queue.add(obj_id)

                    download_queue.append({
                        "obj_id": obj_id,
                        "is_video": item.get("is_video", False),
                        "download_url": item.get("download_url"),
                        "date_str": item_date,
                        "comment": item.get("comment_text", "")
                    })

            if not download_queue:
                self.log(f"No new media items to download in timeframe '{tf_text}'.")
                # Explicit check if we should halt before next month
                if self.sync_mode in ("incremental", "custom"):
                    if found_previously_downloaded:
                        self.log(f"[Incremental Sync] Found previously downloaded pictures in timeframe '{tf_text}'. Halting extraction for {child_name}.")
                        break
                    if reached_custom_start_date:
                        self.log(f"[Custom Sync] Reached custom start date cutoff ({self.start_date}) in timeframe '{tf_text}'. Halting extraction for {child_name}.")
                        break
                continue

            # Calculate 2-digit zero-padded sequence numbers per date ((01), (02), ...)
            date_counters = {}
            current_manifest = self.tenant_storage.load_manifest()
            for m in current_manifest.values():
                if m.get("child") == child_name and m.get("date"):
                    d = m.get("date")
                    date_counters[d] = date_counters.get(d, 0) + 1

            for task in download_queue:
                d = task["date_str"]
                date_counters[d] = date_counters.get(d, 0) + 1
                task["seq"] = date_counters[d]

            self.log(f"Starting parallel download for {len(download_queue)} items in timeframe {tf_text}...")

            # Concurrent Multi-Threaded Task Execution (max_workers=32 for high throughput downloads)
            def _download_task(task_info):
                if self._cancelled:
                    return False

                o_id = task_info["obj_id"]
                d_url = task_info["download_url"]
                d_str = task_info["date_str"]
                seq_num = task_info["seq"]
                is_vid = task_info["is_video"]
                comment_txt = task_info["comment"] or f"Bright Horizons photo for {child_name} on {d_str}"
                
                if d_url.startswith("/"):
                    d_url = f"https://mybrightday.brighthorizons.com{d_url}"

                req_headers = {
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                    "Referer": "https://mybrightday.brighthorizons.com/dashboard/parents.html"
                }

                session_cookies = {}
                try:
                    for c in context.cookies():
                        session_cookies[c["name"]] = c["value"]
                except Exception:
                    pass
                if not session_cookies:
                    try:
                        state_path = os.path.join(self.tenant_storage.tenant_dir, "user_data", "storage_state.json")
                        if os.path.exists(state_path):
                            with open(state_path, "r", encoding="utf-8") as sf:
                                st = json.load(sf)
                                session_cookies = {c["name"]: c["value"] for c in st.get("cookies", [])}
                    except Exception:
                        pass

                file_bytes = None
                mime_type = "video/mp4" if is_vid else "image/jpeg"

                self.log(f"Fetching direct GCS asset for {child_name} {d_str} ({seq_num:02d}) [obj_id: {o_id[:8]}...]...")

                k_id = task_info.get("key_id") or o_id
                fallback_url = f"https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj={o_id}&key={k_id}"

                # Sanitize d_url: ensure primary media download never requests thumbnail assets
                if d_url:
                    if "thumbnail=" in d_url.lower():
                        if "obj_attachment" in d_url:
                            d_url = re.sub(r'[\?&]thumbnail=(true|false|1|0)', '', d_url, flags=re.IGNORECASE).replace("?&", "?").rstrip("?&")
                        else:
                            d_url = fallback_url

                # Exponential backoff retries: 1s, 2s, 4s, 8s, 16s, 30s cap
                backoff_delays = [1.0, 2.0, 4.0, 8.0, 16.0, 30.0]
                for attempt, delay in enumerate(backoff_delays):
                    try:
                        target_url = d_url if (attempt == 0 and d_url and "thumbnail=" not in d_url.lower()) else fallback_url
                        resp = requests.get(target_url, headers=req_headers, cookies=session_cookies, timeout=60)
                        if resp.status_code != 200 and target_url != fallback_url:
                            self.log(f"[Download Notice] Primary URL HTTP {resp.status_code} for obj_id {o_id[:8]}. Requesting fresh signed URL from backend...")
                            target_url = fallback_url
                            resp = requests.get(target_url, headers=req_headers, cookies=session_cookies, timeout=60)

                        if resp.status_code != 200:
                            raise Exception(f"HTTP {resp.status_code} {resp.reason}")

                        body_content = resp.content
                        try:
                            json_data = json.loads(body_content.decode("utf-8"))
                            if isinstance(json_data, dict) and "signed_url" in json_data:
                                s_url = json_data["signed_url"]
                                if json_data.get("mime_type"):
                                    mime_type = json_data["mime_type"]
                                s_resp = requests.get(s_url, headers={"User-Agent": req_headers["User-Agent"]}, timeout=60)
                                if s_resp.status_code != 200:
                                    raise Exception(f"Signed URL HTTP {s_resp.status_code}")
                                file_bytes = s_resp.content
                                break
                        except json.JSONDecodeError:
                            file_bytes = body_content
                            h_ct = resp.headers.get("Content-Type", "")
                            if h_ct and "text/html" not in h_ct:
                                mime_type = h_ct
                            break
                        except Exception:
                            file_bytes = body_content
                            break
                    except Exception as req_err:
                        if attempt == len(backoff_delays) - 1:
                            self.log(f"[Download Error] Permanent failure for obj_id {o_id[:8]} after {len(backoff_delays)} attempts: {req_err}")
                        else:
                            self.log(f"[Download Retry #{attempt + 1}/{len(backoff_delays)}] Retrying obj_id {o_id[:8]}... Error: {req_err} (waiting {delay}s)...")
                            time.sleep(delay)

                if not file_bytes:
                    return False

                # Stage 1: In-Flight 200x200 Thumbnail Check & Refetch (up to 2 retries)
                file_bytes, _ = check_and_refetch_if_200x200(
                    file_bytes=file_bytes,
                    o_id=o_id,
                    k_id=k_id,
                    req_headers=req_headers,
                    session_cookies=session_cookies,
                    is_vid=is_vid,
                    max_retries=2,
                    log_func=self.log
                )

                # Detect true file extension via binary magic bytes inspection
                ext = detect_extension(file_bytes, mime_type)
                
                # Zero-padded 2-digit sequence format: <Child Name> <YYYY-MM-DD> (01).<ext>
                filename = f"{child_name} {d_str} ({seq_num:02d}).{ext}"

                saved_entry = self.tenant_storage.add_media_entry(
                    obj_id=o_id,
                    child=child_name,
                    date_str=d_str,
                    original_filename=filename,
                    comment=comment_txt,
                    file_bytes=file_bytes,
                    mime_type=mime_type
                )

                abs_path = os.path.join(self.tenant_storage.tenant_dir, saved_entry["storage_path"])
                set_eastern_timestamp(abs_path, d_str)
                
                self.status["files_downloaded"] += 1
                self.log(f"Fetched direct GCS asset for {child_name} {d_str} ({seq_num:02d}) -> saved as '{filename}' ({len(file_bytes)} bytes).")
                return True

            with ThreadPoolExecutor(max_workers=32) as executor:
                futures = [executor.submit(_download_task, task) for task in download_queue]
                results = [f.result() for f in futures]

            success_count = sum(1 for r in results if r)
            total_expected = len(download_queue)

            if success_count < total_expected:
                err_msg = f"Extraction incomplete for timeframe '{tf_text}': downloaded only {success_count}/{total_expected} assets!"
                self.log(f"[ERROR] {err_msg}")
                self.status["state"] = "failed"
                self.status["error"] = err_msg
                raise RuntimeError(err_msg)

            self.log(f"Completed timeframe {tf_text}: all {success_count}/{total_expected} items successfully downloaded.")

            # Explicit termination check after processing downloads for the timeframe
            if self.sync_mode in ("incremental", "custom"):
                if found_previously_downloaded:
                    self.log(f"[Incremental Sync] Found previously downloaded pictures in timeframe '{tf_text}'. Halting extraction for {child_name} (older months already synced).")
                    break
                if reached_custom_start_date:
                    self.log(f"[Custom Sync] Reached custom start date cutoff ({self.start_date}) in timeframe '{tf_text}'. Halting extraction for {child_name}.")
                    break

    def scroll_and_load(self, page: Page):
        """Scrolls down the page until no new content is loaded to ensure all photos are rendered (ported from working main.py skill code)."""
        last_height = page.evaluate("document.body.scrollHeight")
        no_change_count = 0
        max_scrolls = 50
        scrolls = 0
        
        while scrolls < max_scrolls:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2500)  # Wait for new items to lazy-load
            
            new_height = page.evaluate("document.body.scrollHeight")
            scrolls += 1
            if new_height == last_height:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight - 600)")
                page.wait_for_timeout(500)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)
                
                new_height = page.evaluate("document.body.scrollHeight")
                if new_height == last_height:
                    no_change_count += 1
                    if no_change_count >= 2:
                        break
                else:
                    no_change_count = 0
            else:
                no_change_count = 0
                
            last_height = new_height

def scrape_photos_and_text(page: Any) -> List[Dict[str, str]]:
    """
    Finds all photo/video attachment URLs on the page via in-browser JS evaluation (from working main.py skill code),
    along with rawHref, keyId, objIdParam, isVideo flags, date overlay text, and card comments.
    """
    js_code = """
    () => {
        const items = [];
        const timeline = document.querySelector('div.well.left-panel.pull-left') || document;
        timeline.querySelectorAll('ul.thumbnails li').forEach(li => {
            const a = li.querySelector('a.fancybox');
            let src = '';
            let rawHref = '';
            let isVideo = false;
            if (a) {
                rawHref = a.getAttribute('href') || '';
                src = rawHref;
                if (rawHref.startsWith('#') || (!rawHref.includes('obj_attachment') && !rawHref.startsWith('http'))) {
                    isVideo = true;
                }
            }
            let styleAttr = '';
            const tile = li.querySelector('div.tile.pointable, div.tile');
            if (tile) {
                styleAttr = tile.getAttribute('style') || '';
                if (!src || (!src.includes('obj_attachment') && !src.startsWith('http'))) {
                    const match = styleAttr.match(/url\\(['"]?([^'"]+)['"]?\\)/);
                    if (match) src = match[1];
                }
            }
            
            const fullSearchString = src + ' ' + rawHref + ' ' + styleAttr;
            const keyMatch = fullSearchString.match(/key=([^&"'\\s]+)/);
            const objMatch = fullSearchString.match(/obj=([^&"'\\s]+)/);
            
            const keyId = keyMatch ? keyMatch[1] : '';
            const objIdParam = objMatch ? objMatch[1] : '';
            
            if (src && (src.includes('obj_attachment') || src.includes('/remote/v1/') || src.startsWith('http') || isVideo)) {
                const dateEl = li.querySelector('.header span.name span') || 
                               li.querySelector('span.name span') || 
                               li.querySelector('.header span.name') || 
                               li.querySelector('span.name');
                const dateText = dateEl ? (dateEl.innerText || dateEl.textContent || '').trim() : '';
                
                const footer = li.querySelector('.footer.note');
                const commentText = footer ? (footer.innerText || footer.textContent || '').trim() : '';
                
                items.push({
                    src: src,
                    rawHref: rawHref,
                    keyId: keyId,
                    objIdParam: objIdParam,
                    isVideo: isVideo,
                    dateText: dateText,
                    commentText: commentText
                });
            }
        });
        
        return items;
    }
    """
    return page.evaluate(js_code)

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
    """Inspects magic bytes to determine file extension (ported from main.py skill code)."""
    if not file_bytes:
        return "jpg"
        
    # Check Image Magic Bytes
    if file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if file_bytes.startswith(b"\xff\xd8"):
        return "jpg"
    if file_bytes.startswith(b"RIFF") and file_bytes[8:12] == b"WEBP":
        return "webp"
    if file_bytes.startswith(b"GIF87a") or file_bytes.startswith(b"GIF89a"):
        return "gif"
        
    # Video Check (MP4/MOV container signatures)
    if b"ftypmp4" in file_bytes[:30] or b"ftypisom" in file_bytes[:30] or (len(file_bytes) > 8 and file_bytes[4:8] == b"ftyp") or b"moov" in file_bytes[:64] or b"mdat" in file_bytes[:64]:
        if b"qt  " in file_bytes[:30] or b"ftypqt" in file_bytes[:30]:
            return "mov"
        return "mp4"
        
    # Fallback to headers
    ct = content_type.lower() if content_type else ""
    if "png" in ct:
        return "png"
    elif "heic" in ct:
        return "heic"
    elif "gif" in ct:
        return "gif"
    elif "mp4" in ct:
        return "mp4"
    elif "quicktime" in ct or "mov" in ct:
        return "mov"
    elif "video/webm" in ct or "webm" in ct:
        return "webm"
    elif "video/" in ct:
        return "mp4"
        
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
