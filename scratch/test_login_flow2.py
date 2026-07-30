import os, sys, time, re
from playwright.sync_api import sync_playwright

email = "taccani.massarelli@gmail.com"
password = "xxTJ8i.5J2KUkkK"

user_data_dir = "/tmp/test_user_data_diag2"
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
    
    print("Step 1: Navigating to familyinfocenter.brighthorizons.com/okta/login...")
    page.goto("https://familyinfocenter.brighthorizons.com/okta/login", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    
    # Click Log In on landing page
    login_btn = page.locator("button:has-text('Log In'), a:has-text('Log In')").first
    if login_btn.count() > 0 and login_btn.is_visible():
        print("Clicking Landing Page Log In button...")
        login_btn.click()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

    print(f"Current SSO URL: {page.url}")
    page.screenshot(path="scratch/sso_page_loaded.png")

    # Step 2: Wait for Cloudflare Turnstile to show "Success!"
    print("Waiting for Cloudflare Turnstile to complete...")
    turnstile_success = False
    for i in range(20):
        body_text = page.locator("body").inner_text()
        if "Success!" in body_text:
            print(f"✓ Turnstile auto-verified to Success! (in {i+1} seconds)")
            turnstile_success = True
            break
        elif "Verify you are a human" in body_text:
            print(f"Turnstile requires manual click (attempting frame click)...")
            turnstile_iframe_el = page.locator("iframe[src*='challenges.cloudflare.com']").first
            if turnstile_iframe_el.count() > 0 and turnstile_iframe_el.is_visible():
                box = turnstile_iframe_el.bounding_box()
                if box:
                    page.mouse.click(box['x'] + 30, box['y'] + (box['height'] / 2))
                    page.wait_for_timeout(3000)
        page.wait_for_timeout(1000)

    page.screenshot(path="scratch/sso_turnstile_status.png")

    # Step 3: Type email and press Continue
    print("Typing email into username field...")
    username_inp = page.locator("input[name='username'], input[id='username'], input[type='email']").first
    username_inp.wait_for(state="visible", timeout=10000)
    username_inp.click(force=True)
    username_inp.fill("")
    username_inp.type(email, delay=50)
    page.wait_for_timeout(1000)

    print("Clicking Continue...")
    cont_btn = page.locator("button._button-login-id, button[type='submit']:not(.ulp-hidden-form-submit-button), button[name='action'], button:has-text('Continue')").first
    cont_btn.click(force=True)

    page.wait_for_timeout(4000)
    page.screenshot(path="scratch/sso_post_email.png")

    # Step 4: Type password and press Continue
    pwd_inp = page.locator("input[name='password']:not(.hide), input[id='password']").first
    print("Waiting for password field...")
    try:
        pwd_inp.wait_for(state="visible", timeout=10000)
        print("Password field appeared! Typing password...")
        pwd_inp.click(force=True)
        pwd_inp.fill(password)
        page.wait_for_timeout(500)
        
        login_btn = page.locator("button[type='submit']:not(.ulp-hidden-form-submit-button), button[name='action'], button:has-text('Log In'), button:has-text('Sign In'), button:has-text('Continue')").first
        login_btn.click(force=True)
        print("Clicked Log In after entering password.")
    except Exception as e:
        print(f"Error waiting for password field: {e}")
        print("Page HTML text snippet:")
        print(page.locator("body").inner_text()[:400])

    page.wait_for_timeout(5000)
    page.screenshot(path="scratch/sso_post_password.png")
    print(f"Final URL: {page.url}")
    print("Body text post password:")
    print(page.locator("body").inner_text()[:600])

    context.close()
