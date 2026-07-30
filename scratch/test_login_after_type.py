import os, sys, time, re
from playwright.sync_api import sync_playwright

email = "taccani.massarelli@gmail.com"
password = "xxTJ8i.5J2KUkkK"

user_data_dir = "/tmp/test_user_data_after_type"
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
    
    login_btn = page.locator("button:has-text('Log In'), a:has-text('Log In')").first
    if login_btn.count() > 0 and login_btn.is_visible():
        print("Step 2: Clicking Landing Page Log In button...")
        login_btn.click()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

    print(f"SSO Page URL: {page.url}")

    # Step 3: Type email FIRST
    print("Step 3: Typing email into username field...")
    username_inp = page.locator("input[name='username'], input[id='username'], input[type='email']").first
    username_inp.wait_for(state="visible", timeout=15000)
    username_inp.click(force=True)
    username_inp.fill("")
    username_inp.type(email, delay=50)
    page.wait_for_timeout(1000)

    page.screenshot(path="scratch/after_typing_email_before_turnstile.png")

    # Step 4: Now solve/wait for Turnstile
    print("Step 4: Monitoring/Solving Cloudflare Turnstile after typing email...")
    for sec in range(25):
        body_text = page.locator("body").inner_text()
        body_lower = body_text.lower()
        
        if "success!" in body_lower or "success" in body_lower:
            print(f"✓ Cloudflare Turnstile SUCCESS detected (sec {sec+1})!")
            break
        elif "verify you are human" in body_lower or "verify you are a human" in body_lower:
            print(f"Turnstile shows 'Verify you are human' (sec {sec+1}). Clicking iframe...")
            turnstile_iframe = page.locator("iframe[src*='challenges.cloudflare.com']").first
            if turnstile_iframe.count() > 0 and turnstile_iframe.is_visible():
                box = turnstile_iframe.bounding_box()
                if box:
                    print(f"Clicking Turnstile iframe at position ({box['x']+30}, {box['y']+box['height']/2})...")
                    page.mouse.click(box['x'] + 30, box['y'] + (box['height'] / 2))
                    page.wait_for_timeout(3000)
        elif "verifying" in body_lower:
            print(f"Turnstile currently verifying... ({sec+1}s)")
            
        page.wait_for_timeout(1000)

    page.screenshot(path="scratch/turnstile_solved_after_email.png")

    # Step 5: Click Continue
    print("Step 5: Clicking Continue button...")
    cont_btn = page.locator("button._button-login-id, button[type='submit']:not(.ulp-hidden-form-submit-button), button[name='action'], button:has-text('Continue')").first
    cont_btn.click(force=True)
    page.wait_for_timeout(4000)

    page.screenshot(path="scratch/post_continue_click.png")
    body_text = page.locator("body").inner_text()
    print("Post continue body snippet:")
    print(body_text[:500])

    # Step 6: Check for password field
    pwd_inp = page.locator("input[name='password']:not(.hide), input[id='password']").first
    try:
        pwd_inp.wait_for(state="visible", timeout=15000)
        print("🎉 SUCCESS! Password field visible! Typing password...")
        pwd_inp.click(force=True)
        pwd_inp.fill(password)
        page.wait_for_timeout(500)
        
        login_btn = page.locator("button[type='submit']:not(.ulp-hidden-form-submit-button), button[name='action'], button:has-text('Log In'), button:has-text('Sign In'), button:has-text('Continue')").first
        login_btn.click(force=True)
        print("Clicked Log In button after entering password.")
    except Exception as e:
        print(f"Password field error: {e}")

    page.wait_for_timeout(5000)
    page.screenshot(path="scratch/final_post_password.png")
    context.close()
