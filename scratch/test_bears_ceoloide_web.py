import os
import sys
import time
from playwright.sync_api import sync_playwright

def test_bears_ceoloide_web():
    email = "taccani.massarelli@gmail.com"
    pwd = "xxTJ8i.5J2KUkkK"
    target_url = "https://bears.ceoloide.com"

    print(f"[WebDiag] Testing UI login flow on {target_url}...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()

        # Listen to network requests & console logs
        page.on("console", lambda msg: print(f"[Console] {msg.type}: {msg.text}"))
        page.on("response", lambda resp: print(f"[HTTP {resp.status}] {resp.url}"))

        print("\n--- STEP 1: Opening Web UI ---")
        page.goto(target_url, wait_until="networkidle")
        time.sleep(2.0)
        print(f"Current page URL: {page.url}")
        print(f"LocalStorage bh_token: {page.evaluate('() => localStorage.getItem(\"bh_token\")')}")
        print(f"LocalStorage bh_email: {page.evaluate('() => localStorage.getItem(\"bh_email\")')}")
        page.screenshot(path="scratch/bears_ui_step1_load.png")

        # Check if we are on Dashboard or LoginForm
        if page.locator("input[type='password']").count() == 0:
            print("[WebDiag] Currently logged in / on Dashboard! Clicking Logout to test fresh login...")
            logout_btn = page.locator("button:has-text('Log Out'), button:has-text('Sign Out')").first
            if logout_btn.count() > 0 and logout_btn.is_visible():
                logout_btn.click()
                time.sleep(2.0)
                print(f"Post-logout LocalStorage bh_token: {page.evaluate('() => localStorage.getItem(\"bh_token\")')}")
                page.screenshot(path="scratch/bears_ui_post_logout.png")

        print("\n--- STEP 2: Submitting LoginForm ---")
        email_inp = page.locator("input[type='text'], input[placeholder*='mail']").first
        pwd_inp = page.locator("input[type='password']").first

        if email_inp.count() > 0 and pwd_inp.count() > 0:
            print("Filling email & password into UI input fields...")
            email_inp.fill(email)
            pwd_inp.fill(pwd)
            page.screenshot(path="scratch/bears_ui_step2_filled.png")

            submit_btn = page.locator("button[type='submit']").first
            print("Clicking 'Log In' submit button...")
            start_submit_time = time.time()
            submit_btn.click()

            # Monitor progress steps & screenshots on VerificationInterstitial for 30s
            for sec in range(40):
                time.sleep(1.0)
                elapsed = round(time.time() - start_submit_time, 2)
                curr_url = page.url
                h1_text = page.locator("h1, h2, .text-xl").inner_text() if page.locator("h1, h2, .text-xl").count() > 0 else ""
                body_snippet = page.locator("body").inner_text()[:300].replace("\n", " ")
                print(f"[{elapsed}s] Heading: '{h1_text}' | Body: {body_snippet[:150]}")
                page.screenshot(path=f"scratch/bears_ui_progress_{sec}s.png")

                # If dashboard reached or error shown, break
                if "Dashboard" in h1_text or "Active Extraction" in body_snippet or page.locator("button:has-text('Log Out')").count() > 0:
                    print(f"\n🎉 Dashboard reached in {elapsed}s!")
                    break

        browser.close()

if __name__ == "__main__":
    test_bears_ceoloide.web() if hasattr(sys.modules[__name__], 'test_bears_ceoloide') else test_bears_ceoloide_web()
