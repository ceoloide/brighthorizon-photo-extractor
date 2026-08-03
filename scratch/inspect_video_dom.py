import os
import sys
import time
import json
import re
import html
from playwright.sync_api import sync_playwright

def inspect_may_2026():
    from backend.database import TenantStorage
    from backend.dom_parser import extract_obj_id_from_url_or_style
    from backend.scraper_engine import parse_date, ensure_xvfb_display, ScraperJob

    ensure_xvfb_display()

    tenant_folder = "9a5ad94325f507c8e3a3be8acb60c06c7b8d3159e1de639145a6c571b116a63e"
    tenant = TenantStorage(tenant_folder)
    config = tenant.load_config()
    pwd = config.get("password")
    job = ScraperJob(tenant, pwd, {})

    print("Bypassing Cloudflare via FlareSolverr...")
    clearance_cookies, solver_ua = job.solve_cloudflare_flaresolverr("https://familyinfocenter.brighthorizons.com/home")
    
    user_data_dir = tenant.user_data_dir
    print(f"User data dir: {user_data_dir}")
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        if clearance_cookies:
            context.add_cookies(clearance_cookies)
            
        page = context.pages[0] if context.pages else context.new_page()
        
        print("Navigating to Family Information Center home...")
        page.goto("https://familyinfocenter.brighthorizons.com/home", wait_until="domcontentloaded")
        try:
            page.wait_for_selector("span:has-text('Actions'), h1", timeout=30000)
        except Exception:
            pass
        time.sleep(4)
        
        if "login" in page.url or "okta" in page.url:
            print("Session expired, logging in...")
            pwd = config.get("password")
            from backend.scraper_engine import ScraperJob
            job = ScraperJob(tenant, pwd, {})
            job.perform_login(page)
            print(f"Logged in successfully. URL: {page.url}")
        else:
            print(f"Session active on familyinfocenter! (URL: {page.url})")
            
        print("Triggering SSO transition from Family Information Center to My Bright Day...")
        try:
            page.wait_for_selector("span:has-text('Actions')", timeout=20000)
        except Exception:
            pass
        spans = page.locator("span", has_text="Actions").all()
        print(f"Found {len(spans)} Actions span buttons on page.")
        
        mbd_page = None
        for idx, span in enumerate(spans):
            card_name = span.evaluate("""(el) => {
                let current = el;
                while (current && current.tagName !== 'BODY') {
                    let h1 = current.querySelector('h1');
                    if (h1 && h1.textContent.trim()) return h1.textContent.trim();
                    current = current.parentElement;
                }
                return '';
            }""")
            print(f"Card #{idx+1} name: '{card_name}'")
            if "byron" in card_name.lower():
                print(f"Clicking Actions for Byron ({card_name})...")
                span.click()
                time.sleep(2)
                mbd_item = page.locator("span.actions-menu-item-label", has_text="My Bright Day").first
                if mbd_item.is_visible():
                    with context.expect_page() as new_page_info:
                        mbd_item.evaluate("(el) => (el.closest('a') || el.closest('button') || el).click()")
                    mbd_page = new_page_info.value
                    mbd_page.wait_for_load_state("domcontentloaded")
                    time.sleep(6)
                    print(f"Successfully opened My Bright Day via SSO! URL: {mbd_page.url}")
                    break
                    
        if not mbd_page:
            print("Failed to open My Bright Day via SSO!")
            return
            
        page = mbd_page
        
        # Click timeframe tile matching may
        tf_lis = page.locator("li").all()
        target_tf = None
        all_tf_texts = []
        for li in tf_lis:
            try:
                txt = li.inner_text().strip().lower()
                if re.match(r'^[a-z]{3}\s+\d{4}$', txt) or "may" in txt:
                    all_tf_texts.append(txt)
                    if "may" in txt:
                        target_tf = li
                        print(f"Found matching May timeframe tile: '{txt}'")
            except Exception:
                pass
                
        print(f"All timeframe tiles found on page: {all_tf_texts}")
        if target_tf:
            tile = target_tf.locator("div.tile.pointable").first
            if tile.count() > 0:
                tile.click()
            else:
                target_tf.click()
            time.sleep(5)
        else:
            print("No 'May' timeframe tile found!")
            
        print("Scrolling feed to trigger full lazy loading...")
        prev_count = 0
        scroll_attempts = 0
        timeline = page.locator("div.well.left-panel.pull-left")
        
        while scroll_attempts < 40:
            scroll_attempts += 1
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2.0)
            page.evaluate("window.scrollBy(0, -600);")
            time.sleep(0.5)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2.0)
            
            feed_items = timeline.locator("ul.thumbnails li").all() if timeline.count() > 0 else page.locator("ul.thumbnails li").all()
            curr_count = len(feed_items)
            print(f"Scroll iteration #{scroll_attempts}: loaded {curr_count} feed posts (prev: {prev_count})")
            if curr_count == prev_count and scroll_attempts > 8:
                print(f"Feed post count stabilized at {curr_count} items.")
                break
            prev_count = curr_count

        feed_items = timeline.locator("ul.thumbnails li").all() if timeline.count() > 0 else page.locator("ul.thumbnails li").all()
        print(f"\n==========================================")
        print(f"TOTAL FEED POSTS DETECTED IN MAY: {len(feed_items)}")
        print(f"==========================================")
        
        video_count = 0
        photo_count = 0
        error_count = 0
        
        for idx, item in enumerate(feed_items):
            try:
                item_html = item.inner_html()
                fancybox = item.locator("a.fancybox").first
                if fancybox.count() == 0:
                    print(f"Post #{idx+1}: NO fancybox anchor found!")
                    continue
                    
                raw_href = fancybox.get_attribute("href") or ""
                pointable_tile = item.locator("div.tile.pointable, div.tile").first
                style_attr = pointable_tile.get_attribute("style") or "" if pointable_tile.count() > 0 else ""
                
                obj_id, is_video, resolved_url = extract_obj_id_from_url_or_style(raw_href, style_attr)
                
                has_video_tag = "<video" in item_html.lower() or "video" in item_html.lower() or "play" in item_html.lower() or raw_href.startswith("#")
                
                if is_video or has_video_tag:
                    video_count += 1
                else:
                    photo_count += 1
                    
                resolved_clean = html.unescape(resolved_url).strip()
                if resolved_clean.startswith("http"):
                    download_url = resolved_clean
                elif resolved_clean.startswith("/"):
                    download_url = f"https://mybrightday.brighthorizons.com{resolved_clean}"
                else:
                    download_url = f"https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj={obj_id}&key={obj_id}"
                
                # Test request get
                resp = page.request.get(download_url, timeout=15000)
                status_code = resp.status
                content_type = resp.headers.get("content-type", "")
                
                if status_code != 200:
                    error_count += 1
                    print(f"\n❌ [ERROR] Post #{idx+1} (obj_id: {obj_id}) returned HTTP {status_code}!")
                    print(f"   raw_href: '{raw_href}'")
                    print(f"   style: '{style_attr}'")
                    print(f"   is_video: {is_video}, has_video_tag: {has_video_tag}")
                    print(f"   download_url: {download_url}")
                    print(f"   Item HTML snippet: {item_html[:300]}...")
                else:
                    if is_video or has_video_tag or idx < 5 or "6a020ff4" in str(obj_id):
                        print(f"Post #{idx+1}: obj_id={obj_id} | is_vid={is_video} | HTTP {status_code} | CT={content_type} | href={raw_href[:40]}")
                        
            except Exception as e:
                print(f"Post #{idx+1} exception: {e}")
                
        print("\n==========================================")
        print(f"SUMMARY FOR MAY FOR BYRON:")
        print(f"Total posts detected: {len(feed_items)}")
        print(f"Photos count: {photo_count}")
        print(f"Videos count: {video_count}")
        print(f"HTTP Errors count: {error_count}")
        print("==========================================")

if __name__ == "__main__":
    inspect_may_2026()
