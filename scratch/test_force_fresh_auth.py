import os
import sys
import time
from playwright.sync_api import sync_playwright

def test_fresh_auth():
    from backend.database import TenantStorage
    from backend.scraper_engine import ScraperJob, ensure_xvfb_display

    ensure_xvfb_display()
    
    tenant_folder = "9a5ad94325f507c8e3a3be8acb60c06c7b8d3159e1de639145a6c571b116a63e"
    tenant = TenantStorage(tenant_folder)
    config = tenant.load_config()
    pwd = config.get("password")
    
    user_data_dir = tenant.user_data_dir
    print(f"Testing fresh auth on user_data_dir: {user_data_dir}")
    
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"]
        )
        page = context.pages[0] if context.pages else context.new_page()
        
        # 1. First navigate to Auth0 logout & Okta logout endpoints
        print("Navigating to Auth0 & Okta logout endpoints...")
        try:
            page.goto("https://bhloginsso.brighthorizons.com/v2/logout", wait_until="domcontentloaded", timeout=10000)
            time.sleep(1.5)
        except Exception as e:
            print(f"Auth0 logout note: {e}")
            
        try:
            page.goto("https://familyinfocenter.brighthorizons.com/okta/logout", wait_until="domcontentloaded", timeout=10000)
            time.sleep(1.5)
        except Exception as e:
            print(f"Okta logout note: {e}")

        # 2. Clear LocalStorage and SessionStorage across origins
        print("Clearing client storage across origins...")
        context.clear_cookies()
        
        # 3. Now navigate to okta/login
        print("Navigating to https://familyinfocenter.brighthorizons.com/okta/login...")
        page.goto("https://familyinfocenter.brighthorizons.com/okta/login", wait_until="domcontentloaded")
        time.sleep(4.0)
        
        print(f"Current page URL: {page.url}")
        
        job = ScraperJob(tenant, pwd, {})
        state = job.detect_page_state(page)
        print(f"Detected page state post-logout: '{state}'")
        
        username_inp = page.locator("input[name='username'], input[id='username'], input[type='email']")
        print(f"Is username input visible? {username_inp.count() > 0 and username_inp.first.is_visible()}")

if __name__ == "__main__":
    test_fresh_auth()
