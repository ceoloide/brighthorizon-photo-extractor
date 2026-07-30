from playwright.sync_api import sync_playwright
import os, time

if not os.environ.get("DISPLAY"):
    os.system("Xvfb :99 -screen 0 1280x720x24 > /dev/null 2>&1 &")
    os.environ["DISPLAY"] = ":99"
    time.sleep(1)

with sync_playwright() as p:
    args = [
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
        "--window-size=1280,720"
    ]
    
    context = p.chromium.launch_persistent_context(
        "/tmp/turnstile_frame_click_dir",
        executable_path="/usr/bin/chromium",
        headless=False,
        args=args,
        ignore_default_args=["--enable-automation"]
    )
    
    page = context.new_page()
    print("1. Navigating to /okta/login...")
    page.goto("https://familyinfocenter.brighthorizons.com/okta/login", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    
    login_btn = page.locator("button:has-text('Log In'), a:has-text('Log In')").first
    print("2. Clicking Log In...")
    login_btn.click(force=True)
    page.wait_for_timeout(3000)
    print("Auth0 URL:", page.url)
    
    username_inp = page.locator("input[name='username']").first
    username_inp.wait_for(state="visible", timeout=25000)
    print("3. Filling email...")
    username_inp.fill("taccani.massarelli@gmail.com")
    page.wait_for_timeout(1000)
    
    # Locate Cloudflare Turnstile iframe frame
    cf_frame = None
    for f in page.frames:
        if "challenges.cloudflare.com" in f.url:
            cf_frame = f
            break
            
    if cf_frame:
        print("4. Found Turnstile iframe:", cf_frame.url)
        try:
            # Click the checkbox inside Turnstile frame
            print("Clicking Turnstile frame position x=30, y=30...")
            cf_frame.click("body", position={"x": 30, "y": 30}, force=True)
            page.wait_for_timeout(4000)
        except Exception as e:
            print("Turnstile frame click exception:", e)
    else:
        print("No Turnstile frame found before submit.")
        
    cont_btn = page.locator("button._button-login-id, button[type='submit']:not(.ulp-hidden-form-submit-button)").first
    print("5. Clicking Continue...")
    cont_btn.click(force=True)
    page.wait_for_timeout(5000)
    
    pwd_inp = page.locator("input[name='password']:not(.hide), input[id='password']").first
    print("6. Password input count:", pwd_inp.count(), "is_visible:", pwd_inp.first.is_visible() if pwd_inp.count() > 0 else False)
    if pwd_inp.count() > 0 and pwd_inp.first.is_visible():
        print("SUCCESS! Turnstile checkbox click revealed password input!")
        pwd_inp.fill("xxTJ8i.5J2KUkkK")
        page.wait_for_timeout(500)
        login_btn = page.locator("button._button-login-id, button[type='submit']:not(.ulp-hidden-form-submit-button)").first
        login_btn.click(force=True)
        page.wait_for_timeout(6000)
        print("Post login URL:", page.url)
        print("Actions span count:", page.locator("span:has-text('Actions')").count())
    else:
        print("Errors:", [e.inner_text() for e in page.locator(".ulp-input-error-message, .alert, .error, p.error").all()])
