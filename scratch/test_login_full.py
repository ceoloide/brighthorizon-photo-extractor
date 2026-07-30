import os, sys, time, re
from playwright.sync_api import sync_playwright

email = "taccani.massarelli@gmail.com"
password = "xxTJ8i.5J2KUkkK"

user_data_dir = "/tmp/test_user_data_full"
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
    
    # Click Log In on landing page if present
    login_btn = page.locator("button:has-text('Log In'), a:has-text('Log In'), button:has-text('Sign In'), a:has-text('Sign In')").first
    if login_btn.count() > 0 and login_btn.is_visible():
        print("Clicking Landing Page Log In button...")
        login_btn.click()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

    print(f"Current SSO URL: {page.url}")

    # Wait for Turnstile auto-verification (or click checkbox if 'Verify you are human' appears)
    print("Step 2: Checking Cloudflare Turnstile status...")
    for i in range(15):
        body_text = page.locator("body").inner_text()
        if "Success!" in body_text:
            print(f"✓ Turnstile auto-verified (Success!) after {i+1} seconds!")
            break
        elif "Verify you are a human" in body_text:
            print("Turnstile shows 'Verify you are human'. Clicking Turnstile checkbox...")
            try:
                turnstile_iframe = page.locator("iframe[src*='challenges.cloudflare.com']").first
                if turnstile_iframe.count() > 0 and turnstile_iframe.is_visible():
                    box = turnstile_iframe.bounding_box()
                    if box:
                        page.mouse.click(box['x'] + 30, box['y'] + (box['height'] / 2))
                        page.wait_for_timeout(3000)
            except Exception as e:
                print(f"Turnstile click notice: {e}")
        page.wait_for_timeout(1000)

    # Step 3: Type email and press Continue
    print("Step 3: Typing email into username field...")
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

    # Step 4: Type password and press Continue
    pwd_inp = page.locator("input[name='password']:not(.hide), input[id='password']").first
    print("Step 4: Waiting for password field...")
    try:
        pwd_inp.wait_for(state="visible", timeout=15000)
        print("Password field visible! Typing password...")
        pwd_inp.click(force=True)
        pwd_inp.fill(password)
        page.wait_for_timeout(500)
        
        login_btn = page.locator("button[type='submit']:not(.ulp-hidden-form-submit-button), button[name='action'], button:has-text('Log In'), button:has-text('Sign In'), button:has-text('Continue')").first
        login_btn.click(force=True)
        print("Clicked Log In button after entering password.")
    except Exception as e:
        print(f"Password field wait error: {e}")

    page.wait_for_timeout(5000)
    print(f"Post-password URL: {page.url}")
    body_text = page.locator("body").inner_text()
    page.screenshot(path="scratch/post_password.png")

    # Step 5: Check for MFA or portal completion
    if "Verify your identity" in body_text or "code" in page.url.lower() or page.locator("input[name='code']").count() > 0:
        print("Step 5: MFA Verification Code Required!")
        remember_chk = page.locator("input[type='checkbox'], label:has-text('Remember')").first
        if remember_chk.count() > 0 and remember_chk.is_visible():
            print("Checking 'Remember this device for 30 days'...")
            remember_chk.click(force=True)
            
        page.screenshot(path="scratch/mfa_screen.png")
        print("Waiting 120s for code input in scratch/mfa_code.txt or terminal...")
        
        # Read MFA code from file if provided, or wait
        mfa_code = None
        for _ in range(120):
            if os.path.exists("scratch/mfa_code.txt"):
                with open("scratch/mfa_code.txt", "r") as f:
                    mfa_code = f.read().strip()
                if len(mfa_code) == 6 and mfa_code.isdigit():
                    print(f"Found MFA code: {mfa_code}")
                    break
            time.sleep(1)

        if mfa_code:
            code_inp = page.locator("input[name='code'], input[id='code'], input[type='text']").first
            code_inp.fill(mfa_code)
            page.wait_for_timeout(500)
            
            submit_btn = page.locator("button[type='submit']:not(.ulp-hidden-form-submit-button), button:has-text('Continue'), button:has-text('Verify')").first
            submit_btn.click(force=True)
            page.wait_for_timeout(5000)
            
    # Check portal home
    print("Checking portal page load...")
    page.wait_for_timeout(5000)
    print(f"Portal URL: {page.url}")
    body_text = page.locator("body").inner_text()
    if "Byron" in body_text or "Actions" in body_text:
        print("SUCCESS! Discovered Byron / child cards on portal page!")
    else:
        print("Portal snippet:")
        print(body_text[:500])

    page.screenshot(path="scratch/portal_final.png")
    context.close()
