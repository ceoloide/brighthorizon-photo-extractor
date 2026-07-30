import os, sys, time, re
from playwright.sync_api import sync_playwright

email = "taccani.massarelli@gmail.com"
password = "xxTJ8i.5J2KUkkK"

user_data_dir = "/tmp/test_user_data_diag3"
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
        print("Clicking Landing Page Log In button...")
        login_btn.click()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

    print(f"Current SSO URL: {page.url}")

    # Type email FIRST
    print("Typing email into username field...")
    username_inp = page.locator("input[name='username'], input[id='username'], input[type='email']").first
    username_inp.wait_for(state="visible", timeout=10000)
    username_inp.click(force=True)
    username_inp.fill("")
    username_inp.type(email, delay=50)
    page.wait_for_timeout(1000)

    # Solve Turnstile if needed
    print("Solving Turnstile frame click...")
    try:
        cf_frame_loc = page.frame_locator("iframe[src*='challenges.cloudflare.com']").locator("body")
        if cf_frame_loc.count() > 0:
            print("Found Turnstile frame locator! Clicking frame body...")
            cf_frame_loc.click()
            page.wait_for_timeout(3000)
    except Exception as e:
        print(f"Frame locator click notice: {e}")

    # Wait for Turnstile Success!
    print("Waiting for Turnstile Success! indicator...")
    for i in range(15):
        body_text = page.locator("body").inner_text()
        if "Success!" in body_text:
            print(f"✓ Turnstile passed (Success!) after {i+1} seconds!")
            break
        page.wait_for_timeout(1000)

    page.screenshot(path="scratch/sso_turnstile_solved.png")

    print("Clicking Continue button...")
    cont_btn = page.locator("button._button-login-id, button[type='submit']:not(.ulp-hidden-form-submit-button), button[name='action'], button:has-text('Continue')").first
    cont_btn.click(force=True)

    page.wait_for_timeout(4000)
    page.screenshot(path="scratch/sso_after_email_continue.png")

    # Password Step
    pwd_inp = page.locator("input[name='password']:not(.hide), input[id='password']").first
    try:
        pwd_inp.wait_for(state="visible", timeout=10000)
        print("Password field appeared! Typing password...")
        pwd_inp.click(force=True)
        pwd_inp.fill(password)
        page.wait_for_timeout(500)
        
        login_btn = page.locator("button[type='submit']:not(.ulp-hidden-form-submit-button), button[name='action'], button:has-text('Log In'), button:has-text('Sign In'), button:has-text('Continue')").first
        login_btn.click(force=True)
        print("Clicked Log In button.")
    except Exception as e:
        print(f"Error waiting for password: {e}")

    page.wait_for_timeout(5000)
    page.screenshot(path="scratch/sso_final_result.png")
    print("Final body text:")
    print(page.locator("body").inner_text()[:600])

    context.close()
