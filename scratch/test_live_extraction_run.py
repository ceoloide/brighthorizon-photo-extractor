import os
import sys
import time
from playwright.sync_api import sync_playwright

def test_live_extraction():
    email = "taccani.massarelli@gmail.com"
    pwd = "xxTJ8i.5J2KUkkK"
    target_url = "https://bears.ceoloide.com"

    print(f"\n=======================================================")
    print(f"🚀 LIVE E2E EXTRACTION JOB TEST ON: {target_url}")
    print(f"=======================================================\n")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        # Step 1: Open live app and log in
        print("Opening https://bears.ceoloide.com...")
        page.goto(target_url, wait_until="networkidle")
        time.sleep(1.5)

        # Logout if logged in
        if page.locator("button:has-text('Log Out'), button:has-text('Sign Out')").count() > 0:
            print("Already logged in. Logging out for clean extraction test...")
            page.locator("button:has-text('Log Out'), button:has-text('Sign Out')").first.click()
            time.sleep(2.0)

        print(f"Submitting credentials ({email})...")
        page.locator("input[type='text'], input[placeholder*='mail']").first.fill(email)
        page.locator("input[type='password']").first.fill(pwd)
        page.locator("button[type='submit']").first.click()

        print("Waiting for Dashboard...")
        page.locator("h2:has-text('Extraction Control Panel'), button:has-text('Log Out')").first.wait_for(timeout=30000)
        time.sleep(2.0)

        # Step 2: Trigger extraction job from Dashboard UI
        start_btn = page.locator("button:has-text('Start Extraction'), button:has-text('Sync Now')").first
        if start_btn.count() > 0 and start_btn.is_visible():
            print("\nClicking 'Start Extraction' button on Dashboard...")
            start_btn.click()
            time.sleep(2.0)

        # Step 3: Monitor extraction status & logs for up to 90 seconds
        print("\n--- Monitoring Live Background Extraction Job ---")
        start_t = time.time()
        fast_path_verified = False
        extraction_success = False

        for sec in range(90):
            time.sleep(1.5)
            elapsed = round(time.time() - start_t, 1)

            body_text = page.locator("body").inner_text()
            
            # Print latest log lines from UI drawer if visible
            log_container = page.locator(".font-mono, pre, code").first
            log_snippet = log_container.inner_text()[:250].replace("\n", " | ") if log_container.count() > 0 else ""
            
            print(f"[{elapsed}s] {log_snippet[:150]}...")

            if "Fast-Path" in body_text or "Fast-Path" in log_snippet or "Filling email address" in log_snippet:
                fast_path_verified = True

            if "completed successfully" in body_text or "Sync complete" in log_snippet or "100%" in body_text:
                extraction_success = True
                print(f"\n🎉 SUCCESS: Extraction completed in {elapsed}s!")
                break

        print("\n--- Extraction Test Results ---")
        print(f"Fast-Path Turnstile Triggered (No 50s Stall): {fast_path_verified}")
        print(f"Extraction Job Completed Successfully: {extraction_success}")

        browser.close()

if __name__ == "__main__":
    test_live_extraction()
