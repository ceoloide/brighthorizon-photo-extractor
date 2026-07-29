# SPDX-License-Identifier: MIT
# Headless Scraper Engine for Bright Horizons Photo Extractor
import json
import os
import re
import sys
import time
import requests
import struct
import zlib
from datetime import datetime, timedelta
from typing import Dict, Any, List, Callable, Optional
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright, BrowserContext, Page
from backend.database import TenantStorage

FLARESOLVERR_URL = os.environ.get("FLARESOLVERR_URL", "http://192.168.1.176:8191/v1")

def capture_b64_screenshot(page: Page) -> Optional[str]:
    """Captures a lightweight base64 JPEG screenshot from Playwright for live visual debug preview."""
    try:
        img_bytes = page.screenshot(type="jpeg", quality=60)
        import base64
        return f"data:image/jpeg;base64,{base64.b64encode(img_bytes).decode('utf-8')}"
    except Exception:
        return None

class ScraperJob:
    def __init__(self, tenant_storage: TenantStorage, password: str, options: Dict[str, Any], log_callback: Optional[Callable[[str], None]] = None):
        self.tenant_storage = tenant_storage
        self.email = tenant_storage.email
        self.password = password
        self.options = options
        self.log_callback = log_callback or (lambda msg: print(f"[{self.email}] {msg}"))
        
        self.sync_mode = options.get("sync_mode", "incremental") # "incremental" or "full"
        self.layout_mode = options.get("layout_mode", "flat") # "flat" or "nested"
        self.target_child = options.get("child", "all")
        
        self.status = {
            "state": "idle", # "idle", "running", "completed", "failed"
            "current_step": "Initializing",
            "files_downloaded": 0,
            "error": None,
            "logs": []
        }

    def log(self, message: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self.status["logs"].append(entry)
        if len(self.status["logs"]) > 200:
            self.status["logs"].pop(0)
        self.log_callback(entry)

    def solve_cloudflare_flaresolverr(self, target_url: str) -> List[Dict[str, Any]]:
        """Queries FlareSolverr API to resolve Cloudflare turnstile/bot challenges and return session cookies."""
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
                    self.log(f"FlareSolverr successfully resolved challenge ({len(cookies)} clearance cookies received).")
                    return cookies
        except Exception as e:
            self.log(f"FlareSolverr request failed (will fall back to native Playwright stealth): {e}")
        return []

    def run(self):
        self.status["state"] = "running"
        self.status["current_step"] = "Starting headless browser"
        self.log("Starting headless extraction job...")
        
        user_data_dir = self.tenant_storage.user_data_dir
        
        try:
            # Query FlareSolverr for initial clearance cookies
            clearance_cookies = self.solve_cloudflare_flaresolverr("https://familyinfocenter.brighthorizons.com/home")
            
            with sync_playwright() as p:
                args = [
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage"
                ]
                
                context: BrowserContext = p.chromium.launch_persistent_context(
                    user_data_dir,
                    headless=True,
                    args=args,
                    ignore_default_args=["--enable-automation"],
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
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

    def perform_login(self, page: Page):
        """Robust headless login handler for Bright Horizons portal & Auth0 SSO."""
        self.log("Navigating to familyinfocenter.brighthorizons.com/home...")
        page.goto("https://familyinfocenter.brighthorizons.com/home", wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        
        # Check if already logged in
        if page.locator("span:has-text('Actions')").count() > 0 or "home" in page.url.lower():
            if page.locator("span:has-text('Actions')").count() > 0:
                self.log("Already authenticated via active browser session!")
                return

        # Check for Log In button on okta landing page
        btn = page.locator("button:has-text('Log In'), a:has-text('Log In'), button:has-text('Sign In')").first
        if btn.count() > 0 and btn.is_visible():
            self.log("Clicking portal Log In button...")
            btn.click()
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(3000)

        # On Auth0 / SSO form
        if "username" in page.content().lower() or "bhloginsso" in page.url.lower():
            self.log("Auth0 SSO form detected. Filling email...")
            
            # Dismiss alert banner if present
            close_btn = page.locator("button:has-text('×'), button[aria-label='Close']").first
            if close_btn.count() > 0 and close_btn.is_visible():
                try: close_btn.click()
                except Exception: pass
                
            username_inp = page.locator("input[name='username'], input[id='username']").first
            username_inp.wait_for(state="visible", timeout=15000)
            username_inp.click()
            username_inp.press_sequentially(self.email, delay=20)
            
            cont_btn = page.locator("button[type='submit']:not(.ulp-hidden-form-submit-button), button._button-login-id").first
            if cont_btn.count() > 0 and cont_btn.is_visible():
                cont_btn.click(force=True)
            else:
                page.keyboard.press("Enter")
                
            page.wait_for_timeout(3000)
            
            pwd_inp = page.locator("input[name='password']:not(.hide), input[id='password']").first
            if pwd_inp.count() > 0:
                pwd_inp.wait_for(state="visible", timeout=10000)
                self.log("Filling password...")
                pwd_inp.click()
                pwd_inp.press_sequentially(self.password, delay=20)
                
                login_btn = page.locator("button[type='submit']:not(.ulp-hidden-form-submit-button), button._button-login-id").first
                if login_btn.count() > 0 and login_btn.is_visible():
                    login_btn.click(force=True)
                else:
                    page.keyboard.press("Enter")
                    
            self.log("Waiting for post-login redirection to portal...")
            try:
                page.wait_for_url(re.compile(r'familyinfocenter|mybrightday|parents\.html|home', re.IGNORECASE), timeout=25000)
            except Exception:
                pass
            page.wait_for_load_state("networkidle", timeout=15000)
            page.wait_for_timeout(2000)
            
            # Check for error elements on SSO form
            error_el = page.locator("span.ulp-input-error-message, div.alert-danger, span#error-element-password").first
            if error_el.count() > 0 and error_el.is_visible():
                err_text = error_el.inner_text().strip()
                raise Exception(f"Authentication failed: {err_text}")
                
            self.log(f"Authenticated state verified! Current URL: {page.url}")

    def verify_credentials(self, progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None) -> List[Dict[str, str]]:
        """
        Standalone pre-verification helper with progress callbacks and live Playwright screenshot capture.
        Validates credentials with Auth0 and auto-discovers children.
        Raises Exception if credentials are invalid or no children found.
        """
        self._last_screenshot_time = 0.0

        def update_progress(step: str, step_index: int, page: Optional[Page] = None, force_shot: bool = False):
            now = time.time()
            shot = None
            if page and (force_shot or (now - self._last_screenshot_time >= 15.0)):
                try:
                    shot = capture_b64_screenshot(page)
                    self._last_screenshot_time = now
                except Exception:
                    pass

            if progress_callback:
                progress_callback({
                    "step": step,
                    "step_index": step_index,
                    "screenshot": shot,
                    "url": getattr(self, "_current_url", "https://familyinfocenter.brighthorizons.com/home")
                })

        def smart_wait(page: Optional[Page], duration_sec: float, step: str, step_index: int):
            start = time.time()
            while time.time() - start < duration_sec:
                time.sleep(1.0)
                now = time.time()
                if page and (now - self._last_screenshot_time >= 15.0):
                    update_progress(step, step_index, page=page, force_shot=True)

        self.log("Starting credentials pre-verification check...")
        update_progress("Bypassing Cloudflare turnstile protection via FlareSolverr...", 1, None, force_shot=False)
        
        user_data_dir = self.tenant_storage.user_data_dir
        clearance_cookies = self.solve_cloudflare_flaresolverr("https://familyinfocenter.brighthorizons.com/home")
        
        with sync_playwright() as p:
            args = [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage"
            ]
            context: BrowserContext = p.chromium.launch_persistent_context(
                user_data_dir,
                headless=True,
                args=args,
                ignore_default_args=["--enable-automation"],
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
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
                update_progress("Navigating to Bright Horizons Auth0 portal...", 2, page=page, force_shot=True)
                smart_wait(page, 15, "Navigating to Bright Horizons Auth0 portal...", 2)
                
                # Step 1: Perform login
                self.log("Navigating to portal and authenticating credentials...")
                self._current_url = "https://familyinfocenter.brighthorizons.com/home"
                
                page.goto("https://familyinfocenter.brighthorizons.com/home", wait_until="domcontentloaded")
                page.wait_for_timeout(2000)
                update_progress("Authenticating with Bright Horizons SSO...", 2, page=page, force_shot=True)
                smart_wait(page, 15, "Authenticating with Bright Horizons SSO...", 2)
                
                self.perform_login(page)
                self._current_url = page.url
                update_progress("Authentication verified! Discovering enrolled children...", 3, page=page, force_shot=True)
                smart_wait(page, 15, "Authentication verified! Discovering enrolled children...", 3)
                
                # Step 2: Auto-discover children
                children = self.discover_children(page, context)
                if not children:
                    config = self.tenant_storage.load_config()
                    children = config.get("children", [])
                    
                if not children:
                    update_progress("Verification failed: No child profiles found.", 3, page=page, force_shot=True)
                    raise Exception("Authentication succeeded, but no active child profiles were discovered for this account.")
                    
                update_progress("Verification complete!", 4, page=page, force_shot=True)
                smart_wait(page, 15, "Verification complete!", 4)
                return children

            except Exception as e:
                update_progress(f"Verification error: {e}", 3, page=page, force_shot=True)
                raise e

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
        
        manifest = self.tenant_storage.load_manifest()
        
        for tf_li in timeframe_lis:
            tf_text = tf_li.inner_text().strip()
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
    """Parses date string into YYYY-MM-DD format."""
    now = datetime.now()
    if not date_text:
        return now.strftime("%Y-%m-%d")
    m = re.search(r'(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?', date_text)
    if m:
        month, day, year = m.groups()
        if not year:
            year = now.year
        else:
            year = int(year)
            if year < 100: year += 2000
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return now.strftime("%Y-%m-%d")

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
