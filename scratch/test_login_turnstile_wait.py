import os, sys, time, re
from playwright.sync_api import sync_playwright

email = "taccani.massarelli@gmail.com"
password = "xxTJ8i.5J2KUkkK"

user_data_dir = "/tmp/test_user_data_turnstile"
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
    
    login_btn = page.locator("button:has-text('Log In'), a:has-text('Log In'), button:has-text('Sign In'), a:has-text('Sign In')").first
    if login_btn.count() > 0 and login_btn.is_visible():
        print("Clicking Landing Page Log In button...")
        login_btn.click()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

    print(f"Current SSO URL: {page.url}")

    # Wait for Turnstile state to become 'Success!' or 'Verify you are human'
    print("Step 2: Monitoring Cloudflare Turnstile box state...")
    turnstile_passed = False
    
    for sec in range(30):
        # Inspect inner text of Turnstile wrapper or page body
        body_text = page.locator("body").inner_text()
        body_lower = body_text.lower()
        
        if "success!" in body_lower or "success" in body_lower:
            print(f"✓ Cloudflare Turnstile SUCCESS detected after {sec+1} seconds!")
            turnstile_passed = True
            break
        elif "verify you are human" in body_lower or "verify you are a human" in body_lower:
            print(f"Turnstile requires click (sec {sec+1}). Attempting click on Turnstile iframe...")
            turnstile_iframe = page.locator("iframe[src*='challenges.cloudflare.com']").first
            if turnstile_iframe.count() > 0 and turnstile_iframe.is_visible():
                box = turnstile_iframe.bounding_box()
                if box:
                    print(f"Clicking Turnstile iframe at position ({box['x']+30}, {box['y']+box['height']/2})...")
                    page.mouse.click(box['x'] + 30, box['y'] + (box['height'] / 2))
                    page.wait_for_timeout(3000)
        elif "verifying" in body_lower:
            print(f"Turnstile currently verifying... waiting ({sec+1}s)")
            
        page.wait_for_timeout(1000)

    page.screenshot(path="scratch/turnstile_state.png")

    # Step 3: Type email and press Continue
    print("Step 3: Typing email address...")
    username_inp = page.locator("input[name='username'], input[id='username'], input[type='email']").first
    username_inp.wait_for(state="visible", timeout=15000)
    username_inp.click(force=True)
    username_inp.fill("")
    username_inp.type(email, delay=50)
    page.wait_for_timeout(1000)

    print("Clicking Continue button...")
    cont_btn = page.locator("button._button-login-id, button[type='submit']:not(.ulp-hidden-form-submit-button), button[name='action'], button:has-text('Continue')").first
    cont_btn.click(force=True)
    page.wait_for_timeout(4000)
    page.screenshot(path="scratch/after_email.png")

    # Step 4: Password
    pwd_inp = page.locator("input[name='password']:not(.hide), input[id='password']").first
    try:
        pwd_inp.wait_for(state="visible", timeout=15000)
        print("✓ Password input visible! Typing password...")
        pwd_inp.click(force=True)
        pwd_inp.fill(password)
        page.wait_for_timeout(500)
        
        login_btn = page.locator("button[type='submit']:not(.ulp-hidden-form-submit-button), button[name='action'], button:has-text('Log In'), button:has-text('Sign In'), button:has-text('Continue')").first
        login_btn.click(force=True)
        print("Clicked Log In button after entering password.")
    except Exception as e:
        print(f"Password field error: {e}")

    page.wait_for_timeout(5000)
    print(f"Post-password URL: {page.url}")
    body_text = page.locator("body").inner_text()
    page.screenshot(path="scratch/after_password.png")

    if "Verify your identity" in body_text or "mfa" in page.url.lower() or page.locator("input[name='code']").count() > 0:
        print("MFA Challenge Screen Detected!")
        remember_chk = page.locator("input[type='checkbox'], label:has-text('Remember')").first
        if remember_chk.count() > 0 and remember_chk.is_visible():
            print("Checking 'Remember this device for 30 days'...")
            remember_chk.click(force=True)
        page.screenshot(path="scratch/mfa_screen.png")

    context.close()
