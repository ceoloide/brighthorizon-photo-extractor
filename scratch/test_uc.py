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
        "--disable-features=IsolateOrigins,site-per-process",
        "--window-size=1280,720"
    ]
    
    # Launch persistent context
    context = p.chromium.launch_persistent_context(
        "/tmp/uc_test_dir",
        executable_path="/usr/bin/chromium",
        headless=False,
        args=args,
        ignore_default_args=["--enable-automation"]
    )
    
    page = context.new_page()
    page.goto("https://familyinfocenter.brighthorizons.com/okta/login", wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    
    login_btn = page.locator("button:has-text('Log In'), a:has-text('Log In')").first
    print("Clicking Log In...")
    login_btn.click(force=True)
    page.wait_for_timeout(3000)
    print("Auth0 URL:", page.url)
    
    # Check if turnstile is iframe or embedded
    print("Iframes on page:", len(page.frames))
    for f in page.frames:
        print(" Frame URL:", f.url)
        
    username_inp = page.locator("input[name='username']").first
    username_inp.wait_for(state="visible", timeout=25000)
    print("Filling email...")
    username_inp.fill("taccani.massarelli@gmail.com")
    page.wait_for_timeout(1000)
    
    cont_btn = page.locator("button._button-login-id, button[type='submit']:not(.ulp-hidden-form-submit-button)").first
    print("Clicking Continue...")
    cont_btn.click(force=True)
    page.wait_for_timeout(5000)
    
    print("Iframes after submit:", len(page.frames))
    for f in page.frames:
        print(" Frame URL:", f.url)
        
    pwd_inp = page.locator("input[name='password']:not(.hide)").first
    print("Password input visible:", pwd_inp.is_visible() if pwd_inp.count() > 0 else False)
    print("Messages:", [e.inner_text() for e in page.locator(".ulp-input-error-message, .alert, .error, p.error").all()])
