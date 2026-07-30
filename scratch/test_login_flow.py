import os, sys, time, re
from playwright.sync_api import sync_playwright

email = "taccani.massarelli@gmail.com"
password = "xxTJ8i.5J2KUkkK"

user_data_dir = "/tmp/test_user_data_diag"
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
    print(f"Current URL: {page.url}")
    
    # Step 2: Click Log In if on landing page
    login_btn = page.locator("button:has-text('Log In'), a:has-text('Log In'), button:has-text('Sign In'), a:has-text('Sign In')").first
    if login_btn.count() > 0 and login_btn.is_visible():
        print("Clicking Landing Page Log In button...")
        login_btn.click()
        page.wait_for_timeout(4000)
        print(f"Post-click URL: {page.url}")

    # Step 3: SSO Page & Cloudflare Turnstile
    username_inp = page.locator("input[name='username'], input[id='username'], input[type='email']").first
    if username_inp.count() > 0 and username_inp.is_visible():
        print("SSO email input field detected.")
        
        # Wait for Turnstile auto-verification ("Success!")
        print("Waiting up to 10s for Turnstile auto-verification...")
        for i in range(10):
            body_text = page.locator("body").inner_text()
            if "Success!" in body_text:
                print("Cloudflare Turnstile auto-verification SUCCESS detected!")
                break
            page.wait_for_timeout(1000)
            
        body_text = page.locator("body").inner_text()
        if "Success!" not in body_text:
            print("Turnstile did not auto-verify into 'Success!'. Checking for Turnstile iframe click...")
            turnstile_iframe_el = page.locator("iframe[src*='challenges.cloudflare.com']").first
            if turnstile_iframe_el.count() > 0 and turnstile_iframe_el.is_visible():
                box = turnstile_iframe_el.bounding_box()
                if box:
                    print(f"Clicking Turnstile iframe checkbox at ({box['x']+30}, {box['y']+box['height']/2})...")
                    page.mouse.click(box['x'] + 30, box['y'] + (box['height'] / 2))
                    page.wait_for_timeout(5000)
                    
        # Type email
        print("Typing email into input field...")
        username_inp.click(force=True)
        username_inp.fill("")
        username_inp.type(email, delay=50)
        page.wait_for_timeout(1000)
        
        # Click Continue
        print("Clicking Continue button...")
        cont_btn = page.locator("button._button-login-id, button[type='submit']:not(.ulp-hidden-form-submit-button), button[name='action'], button:has-text('Continue')").first
        if cont_btn.count() > 0 and cont_btn.is_visible():
            cont_btn.click(force=True)
        else:
            username_inp.press("Enter")
            
        page.wait_for_timeout(4000)
        
    # Step 4: Password
    pwd_inp = page.locator("input[name='password']:not(.hide), input[id='password']").first
    if pwd_inp.count() > 0 and pwd_inp.is_visible():
        print("Password input field detected. Typing password...")
        pwd_inp.click(force=True)
        pwd_inp.fill(password)
        page.wait_for_timeout(500)
        
        login_btn = page.locator("button[type='submit']:not(.ulp-hidden-form-submit-button), button[name='action'], button:has-text('Log In'), button:has-text('Sign In')").first
        if login_btn.count() > 0 and login_btn.is_visible():
            print("Clicking Log In / Continue button...")
            login_btn.click(force=True)
        else:
            pwd_inp.press("Enter")
            
        page.wait_for_timeout(5000)
        print(f"Post-password URL: {page.url}")

    # Step 5: Check if MFA is requested or if logged in
    body_text = page.locator("body").inner_text()
    print("Body text snippet post-login:")
    print(body_text[:500])
    
    if "Verify your identity" in body_text or "code" in page.url.lower():
        print("MFA Challenge Detected!")
        remember_chk = page.locator("input[type='checkbox'], label:has-text('Remember')").first
        if remember_chk.count() > 0 and remember_chk.is_visible():
            print("Checking 'Remember this device for 30 days'...")
            remember_chk.click(force=True)
            
        page.screenshot(path="scratch/mfa_challenge.png")
        print("Saved MFA screenshot to scratch/mfa_challenge.png")
        
    context.close()
