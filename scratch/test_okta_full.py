from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage"
    ]
    context = p.chromium.launch_persistent_context(
        "/tmp/okta_no_init_dir_2",
        headless=True,
        args=args,
        ignore_default_args=["--enable-automation"],
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
    
    page = context.new_page()
    print("1. Navigating to /okta/login...")
    page.goto('https://familyinfocenter.brighthorizons.com/okta/login', wait_until='domcontentloaded')
    page.wait_for_timeout(2000)
    
    login_btn = page.locator("button:has-text('Log In'), a:has-text('Log In')").first
    print("2. Clicking portal Log In button...")
    login_btn.click(force=True)
    page.wait_for_timeout(3000)
    print("URL 2 (Auth0):", page.url)
    
    username_inp = page.locator("input[name='username'], input[id='username'], input[type='email']").first
    username_inp.wait_for(state="visible", timeout=25000)
    print("3. Filling email...")
    username_inp.fill("taccani.massarelli@gmail.com")
    page.wait_for_timeout(500)
    
    cont_btn = page.locator("button._button-login-id, button[type='submit']:not(.ulp-hidden-form-submit-button)").first
    print("4. Clicking Continue button text:", cont_btn.inner_text(), "class:", cont_btn.get_attribute("class"))
    cont_btn.click(force=True)
    page.wait_for_timeout(4000)
    
    print("URL post email submit:", page.url)
    print("Inputs on page:", [f"name='{i.get_attribute('name')}' id='{i.get_attribute('id')}' type='{i.get_attribute('type')}' vis={i.is_visible()}" for i in page.locator("input").all()])
    print("Errors / messages on page:", [e.inner_text() for e in page.locator("span, p, div").all() if "error" in (e.get_attribute("class") or "").lower() or "alert" in (e.get_attribute("class") or "").lower()])
