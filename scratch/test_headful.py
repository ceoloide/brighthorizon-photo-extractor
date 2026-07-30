from playwright.sync_api import sync_playwright
import shutil, os

clean_dir = "/tmp/headful_test_dir_123"
if os.path.exists(clean_dir):
    shutil.rmtree(clean_dir)

with sync_playwright() as p:
    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage"
    ]
    context = p.chromium.launch_persistent_context(
        clean_dir,
        headless=False,
        args=args,
        ignore_default_args=["--enable-automation"],
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    try:
        from playwright_stealth import Stealth
        Stealth().apply_stealth_sync(page)
    except Exception as e:
        print("Stealth notice:", e)
        
    print("Navigating to familyinfocenter...")
    page.goto('https://familyinfocenter.brighthorizons.com/home', wait_until='domcontentloaded')
    page.wait_for_timeout(2000)
    print("URL 1:", page.url)
    
    btn = page.locator("button:has-text('Log In'), a:has-text('Log In')").first
    if btn.count() > 0:
        btn.click(force=True)
        page.wait_for_timeout(3000)
    print("URL 2 (Auth0):", page.url)
    
    username = page.locator("input[name='username']").first
    if username.count() > 0:
        username.fill('taccani.massarelli@gmail.com')
        page.wait_for_timeout(500)
        
        cont = page.locator("button._button-login-id, button[type='submit']:not(.ulp-hidden-form-submit-button)").first
        print("Clicking continue button...")
        cont.click()
        page.wait_for_timeout(4000)
        print("URL 3 post email:", page.url)
        pwd = page.locator("input[name='password']")
        print("Password input count:", pwd.count(), "is_visible:", pwd.first.is_visible() if pwd.count() > 0 else False)
        print("Errors:", [e.inner_text() for e in page.locator(".ulp-input-error-message, .alert, .error, p.error").all()])
