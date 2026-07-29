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
        """Queries FlareSolverr API to resolve Cloudflare challenges and return session cookies."""
        try:
            self.log("Querying FlareSolverr endpoint to bypass Cloudflare protection...")
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
                    self.log(f"FlareSolverr successfully resolved challenge ({len(cookies)} cookies received).")
                    return cookies
        except Exception as e:
            self.log(f"FlareSolverr request failed (will fall back to native Playwright): {e}")
        return []

    def run(self):
        self.status["state"] = "running"
        self.status["current_step"] = "Starting headless browser"
        self.log("Starting headless extraction job...")
        
        user_data_dir = self.tenant_storage.user_data_dir
        
        try:
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
                
                page: Page = context.new_page()
                
                # Step 1: Check login & authenticate
                self.status["current_step"] = "Authenticating with Bright Horizons"
                self.log("Navigating to familyinfocenter.brighthorizons.com/home...")
                page.goto("https://familyinfocenter.brighthorizons.com/home", wait_until="domcontentloaded")
                
                # Check for Cloudflare Turnstile / 403
                title = page.title().lower()
                content = page.content().lower()
                if "just a moment" in title or "cloudflare" in title or "turnstile" in content:
                    self.log("Cloudflare Turnstile detected! Engaging FlareSolverr bypass...")
                    cookies = self.solve_cloudflare_flaresolverr("https://familyinfocenter.brighthorizons.com/home")
                    if cookies:
                        formatted_cookies = []
                        for c in cookies:
                            formatted_cookies.append({
                                "name": c["name"],
                                "value": c["value"],
                                "domain": c["domain"],
                                "path": c.get("path", "/"),
                                "secure": c.get("secure", False)
                            })
                        context.add_cookies(formatted_cookies)
                        page.reload(wait_until="domcontentloaded")
                
                # Perform login if needed
                if "login" in page.url.lower() or page.locator("input[type='email'], input[name='username']").count() > 0:
                    self.log("Login form detected. Entering credentials...")
                    email_input = page.locator("input[type='email'], input[name='username']").first
                    email_input.fill(self.email)
                    
                    next_btn = page.locator("button[type='submit'], input[type='submit'], button:has-text('Next')").first
                    if next_btn.is_visible():
                        next_btn.click()
                        page.wait_for_timeout(2000)
                        
                    pwd_input = page.locator("input[type='password']").first
                    pwd_input.wait_for(state="visible", timeout=10000)
                    pwd_input.fill(self.password)
                    
                    login_btn = page.locator("button[type='submit'], input[type='submit'], button:has-text('Sign In')").first
                    login_btn.click()
                    
                    page.wait_for_load_state("domcontentloaded", timeout=30000)
                    page.wait_for_timeout(3000)
                
                self.log(f"Authenticated successfully! Current URL: {page.url}")
                
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
