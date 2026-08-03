import os
import sys
import time
from playwright.sync_api import sync_playwright

def test_live_bears_ceoloide():
    email = "taccani.massarelli@gmail.com"
    pwd = "xxTJ8i.5J2KUkkK"
    target_url = "https://bears.ceoloide.com"

    print(f"\n=======================================================")
    print(f"🚀 LIVE E2E TEST: Submitting login on {target_url}")
    print(f"=======================================================\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        # Step 1: Open live web app
        print("Opening https://bears.ceoloide.com...")
        page.goto(target_url, wait_until="networkidle")
        time.sleep(1.5)

        # Logout if logged in from previous session
        if page.locator("button:has-text('Log Out'), button:has-text('Sign Out')").count() > 0:
            print("Already logged in. Clicking Log Out to perform fresh login test...")
            page.locator("button:has-text('Log Out'), button:has-text('Sign Out')").first.click()
            time.sleep(2.0)

        # Step 2: Fill login form
        print(f"Filling credentials ({email})...")
        page.locator("input[type='text'], input[placeholder*='mail']").first.fill(email)
        page.locator("input[type='password']").first.fill(pwd)
        page.screenshot(path="scratch/live_test_step1_filled.png")

        print("Clicking 'Log In' button...")
        start_t = time.time()
        page.locator("button[type='submit']").first.click()

        # Step 3: Monitor progress frames for up to 60 seconds
        print("\n--- Monitoring Live Interstitial Progress ---")
        step1_seen = False
        step2_seen = False
        step3_seen = False
        dashboard_reached = False

        for sec in range(60):
            time.sleep(1.0)
            elapsed = round(time.time() - start_t, 1)

            body_text = page.locator("body").inner_text().replace("\n", " ")

            if "STEP 01" in body_text or "Initialize Browser Engine" in body_text:
                step1_seen = True
            if "STEP 02" in body_text or "Authenticate & Verify Identity" in body_text or "Authenticating" in body_text:
                step2_seen = True
            if "STEP 03" in body_text or "Discover Enrolled Children" in body_text or "Discovering" in body_text:
                step3_seen = True

            # Print snapshot every 3 seconds or on key transitions
            if sec % 3 == 0 or "Dashboard" in body_text or "Extraction Control Panel" in body_text:
                print(f"[{elapsed}s] {body_text[:140]}...")
                page.screenshot(path=f"scratch/live_test_progress_{sec}s.png")

            if "Extraction Control Panel" in body_text or "Extracted Media Library" in body_text or page.locator("button:has-text('Log Out')").count() > 0:
                dashboard_reached = True
                print(f"\n🎉 SUCCESS: Live Dashboard reached after {elapsed}s!")
                break

        print("\n--- Test Verification Summary ---")
        print(f"Step 1 (Browser Init) Observed: {step1_seen}")
        print(f"Step 2 (Auth & Verify) Observed: {step2_seen}")
        print(f"Step 3 (Child Discovery) Observed: {step3_seen}")
        print(f"Dashboard Reached: {dashboard_reached}")

        browser.close()

if __name__ == "__main__":
    test_live_bears_ceoloide()
