from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage"
    ]
    context = p.chromium.launch_persistent_context(
        "/tmp/turnstile_click_test_dir",
        headless=True,
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
        
    print("Navigating to /okta/login...")
    page.goto('https://familyinfocenter.brighthorizons.com/okta/login', wait_until='domcontentloaded')
    page.wait_for_timeout(2000)
    
    login_btn = page.locator("button:has-text('Log In'), a:has-text('Log In')").first
    print("Clicking Log In button...")
    login_btn.click(force=True)
    page.wait_for_timeout(3000)
    print("URL on Auth0:", page.url)
    
    username_inp = page.locator("input[name='username'], input[id='username'], input[type='email']").first
    username_inp.wait_for(state="visible", timeout=25000)
    print("Filling email...")
    username_inp.fill("taccani.massarelli@gmail.com")
    page.wait_for_timeout(1000)
    
    # Check for Turnstile iframe
    turnstile_iframe = page.frame_locator("iframe[src*='challenges.cloudflare.com']")
    try:
        cb = turnstile_iframe.locator("input[type='checkbox'], div.mark, #challenge-stage").first
        if cb.count() > 0:
            print("Turnstile iframe detected! Attempting click on Turnstile checkbox...")
            cb.click(force=True)
            page.wait_for_timeout(3000)
        else:
            print("Turnstile checkbox element count is 0 in iframe.")
    except Exception as e:
        print("Turnstile check exception:", e)
        
    cont_btn = page.locator("button._button-login-id, button[type='submit']:not(.ulp-hidden-form-submit-button)").first
    print("Clicking Continue button...")
    cont_btn.click(force=True)
    page.wait_for_timeout(4000)
    
    pwd_inp = page.locator("input[name='password']:not(.hide), input[id='password']").first
    print("Password input count:", pwd_inp.count(), "is_visible:", pwd_inp.first.is_visible() if pwd_inp.count() > 0 else False)
