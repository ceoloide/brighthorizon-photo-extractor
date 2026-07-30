import os, sys, time, re
from playwright.sync_api import sync_playwright

user_data_dir = "/tmp/test_user_data_selectors"
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
    
    page.goto("https://familyinfocenter.brighthorizons.com/okta/login", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    
    login_btn = page.locator("button:has-text('Log In'), a:has-text('Log In')").first
    if login_btn.count() > 0 and login_btn.is_visible():
        login_btn.click()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

    print("SSO page loaded:", page.url)

    # Find Cloudflare iframe
    iframe_loc = page.locator("iframe[src*='challenges.cloudflare.com']").first
    iframe_loc.wait_for(state="visible", timeout=10000)
    box = iframe_loc.bounding_box()
    print("Turnstile Iframe Bounding Box:", box)

    # Strategy A: Use page.mouse.click at exact checkbox center (box['x'] + 28, box['y'] + 28)
    if box:
        click_x = box['x'] + 28
        click_y = box['y'] + (box['height'] / 2)
        print(f"Strategy A: Mouse click at ({click_x}, {click_y})...")
        page.mouse.click(click_x, click_y)
        page.wait_for_timeout(4000)

    page.screenshot(path="scratch/turnstile_strat_a.png")

    body_text = page.locator("body").inner_text()
    print("Body text snippet post Strategy A:")
    print(body_text[:300])

    if "Success!" in body_text:
        print("✓ STRATEGY A WORKED! Turnstile Success!")
    else:
        print("Strategy A did not verify immediately. Trying Strategy B (frame locator click)...")
        frame = page.frame_locator("iframe[src*='challenges.cloudflare.com']")
        try:
            # Click label / checkbox inside frame
            frame.locator("label, input, .cb-i, #challenge-stage").first.click(force=True)
            page.wait_for_timeout(4000)
        except Exception as e:
            print("Strategy B error:", e)

    page.screenshot(path="scratch/turnstile_strat_b.png")
    body_text_b = page.locator("body").inner_text()
    print("Body text snippet post Strategy B:")
    print(body_text_b[:300])

    context.close()
