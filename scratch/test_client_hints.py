from playwright.sync_api import sync_playwright
import os, time

if not os.environ.get("DISPLAY"):
    print("Starting Xvfb display...")
    os.system("Xvfb :99 -screen 0 1280x720x24 > /dev/null 2>&1 &")
    os.environ["DISPLAY"] = ":99"
    time.sleep(1)

with sync_playwright() as p:
    # Use native user-agent & matching client hints (do NOT spoof macOS user agent on Linux binary!)
    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--window-size=1280,720"
    ]
    context = p.chromium.launch_persistent_context(
        "/tmp/native_ua_dir",
        executable_path="/usr/bin/chromium",
        headless=False,
        args=args,
        ignore_default_args=["--enable-automation"]
    )
    
    page = context.new_page()
    print("1. Navigating to /okta/login with native Linux Client Hints...")
    page.goto('https://familyinfocenter.brighthorizons.com/okta/login', wait_until='domcontentloaded')
    page.wait_for_timeout(2000)
    
    login_btn = page.locator("button:has-text('Log In'), a:has-text('Log In')").first
    print("2. Clicking portal Log In button...")
    login_btn.click(force=True)
    page.wait_for_timeout(3000)
    print("URL on Auth0:", page.url)
    
    username_inp = page.locator("input[name='username'], input[id='username'], input[type='email']").first
    username_inp.wait_for(state="visible", timeout=25000)
    print("3. Filling email...")
    username_inp.fill("taccani.massarelli@gmail.com")
    page.wait_for_timeout(1000)
    
    cont_btn = page.locator("button._button-login-id, button[type='submit']:not(.ulp-hidden-form-submit-button)").first
    print("4. Clicking Continue button...")
    cont_btn.click(force=True)
    page.wait_for_timeout(5000)
    
    pwd_inp = page.locator("input[name='password']:not(.hide), input[id='password']").first
    print("5. Checking password field visibility...")
    if pwd_inp.count() > 0 and pwd_inp.first.is_visible():
        print("SUCCESS! Native Linux Client Hints allowed Turnstile to pass!")
        pwd_inp.fill("xxTJ8i.5J2KUkkK")
        page.wait_for_timeout(500)
        
        login_btn = page.locator("button._button-login-id, button[type='submit']:not(.ulp-hidden-form-submit-button)").first
        print("6. Clicking Log In button...")
        login_btn.click(force=True)
        page.wait_for_timeout(7000)
        print("7. Post login URL:", page.url)
        actions = page.locator("span:has-text('Actions')")
        print("8. Actions span count:", actions.count())
    else:
        print("Password field NOT visible. Errors:", [e.inner_text() for e in page.locator(".ulp-input-error-message, .alert, .error, p.error").all()])
