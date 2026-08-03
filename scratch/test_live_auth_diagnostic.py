import os
import sys
import time
from playwright.sync_api import sync_playwright

def run_diagnostic():
    from backend.database import TenantStorage
    from backend.scraper_engine import ScraperJob, ensure_xvfb_display, launch_stealth_persistent_context

    ensure_xvfb_display()

    email = "taccani.massarelli@gmail.com"
    pwd = "xxTJ8i.5J2KUkkK"

    tenant = TenantStorage(email)
    print(f"[Diag] Tenant ID: {tenant.tenant_id}")
    print(f"[Diag] Tenant User Data Dir: {tenant.user_data_dir}")

    # Step 1: Wipe tenant user_data_dir before test to emulate fresh profile
    tenant.clear_session()
    print("[Diag] Tenant session state cleared from disk.")

    with sync_playwright() as p:
        context = launch_stealth_persistent_context(p, tenant.user_data_dir)
        page = context.pages[0] if context.pages else context.new_page()

        job = ScraperJob(tenant, pwd, {})

        print("\n--- STEP 1: Initial Navigation ---")
        print("Navigating to https://familyinfocenter.brighthorizons.com/okta/login...")
        page.goto("https://familyinfocenter.brighthorizons.com/okta/login", wait_until="domcontentloaded")
        time.sleep(3.0)

        print(f"Current URL after initial goto: {page.url}")
        state = job.detect_page_state(page)
        print(f"Detected page state: '{state}'")
        page.screenshot(path="scratch/diag_auth_step1.png")

        print("\n--- STEP 2: Running perform_login ---")
        try:
            job.perform_login(page, force_fresh_auth=True)
            print(f"perform_login completed cleanly! Final URL: {page.url}")
            page.screenshot(path="scratch/diag_auth_step2.png")
        except Exception as e:
            print(f"perform_login raised exception: {e}")
            page.screenshot(path="scratch/diag_auth_error.png")

        print("\n--- STEP 3: Auto-discovering children ---")
        try:
            children = job.discover_children(page, context)
            print(f"Discovered children result: {children}")
            page.screenshot(path="scratch/diag_auth_step3.png")
        except Exception as e:
            print(f"discover_children error: {e}")

        context.close()

if __name__ == "__main__":
    run_diagnostic()
