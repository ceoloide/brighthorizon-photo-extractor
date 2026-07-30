from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    print("Navigating directly to /okta/login...")
    page.goto("https://familyinfocenter.brighthorizons.com/okta/login", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    print("URL post /okta/login:", page.url)
    
    login_btn = page.locator("button:has-text('Log In'), a:has-text('Log In')").first
    print("Log In button count:", login_btn.count())
    if login_btn.count() > 0:
        print("Clicking Log In...")
        login_btn.click(force=True)
        page.wait_for_timeout(4000)
        print("URL post click:", page.url)
        username = page.locator("input[name='username']").first
        print("Username count:", username.count())
