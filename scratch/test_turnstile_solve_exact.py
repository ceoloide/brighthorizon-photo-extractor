import os, sys, time, re
from playwright.sync_api import sync_playwright

email = "taccani.massarelli@gmail.com"
password = "xxTJ8i.5J2KUkkK"

user_data_dir = "/tmp/test_user_data_exact"
os.makedirs(user_data_dir, exist_ok=True)

with sync_playwright() as p:
    print("Launching Chromium headful with Xvfb...")
    context = p.chromium.launch_persistent_context(
        user_data_dir,
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage", "--window-size=1280,720"],
        ignore_default_args=["--enable-automation"]
    )
    page = context.pages[0] if context.pages else context.new_page()
    
    print("Navigating to okta/login...")
    page.goto("https://familyinfocenter.brighthorizons.com/okta/login", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    
    login_btn = page.locator("button:has-text('Log In'), a:has-text('Log In')").first
    if login_btn.count() > 0 and login_btn.is_visible():
        login_btn.click()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

    print("SSO page loaded:", page.url)

    # Let's inspect all frames on the page!
    print("Enumerating frames:")
    for f in page.frames:
        print(" Frame URL:", f.url)

    # Target turnstile frame directly
    turnstile_frame = None
    for f in page.frames:
        if "challenges.cloudflare.com" in f.url or "turnstile" in f.url:
            turnstile_frame = f
            break

    if turnstile_frame:
        print("Found Cloudflare Turnstile frame!")
        try:
            # Click checkbox inside frame
            chk = turnstile_frame.locator("input[type='checkbox'], span.mark, div.ctp-checkbox-label, body").first
            print("Clicking Turnstile checkbox inside frame...")
            chk.click(force=True)
            page.wait_for_timeout(3000)
        except Exception as e:
            print("Frame inner click failed:", e)

    page.screenshot(path="scratch/exact_turnstile_post_click.png")
    print("Post-click text:")
    print(page.locator("body").inner_text()[:400])

    context.close()
