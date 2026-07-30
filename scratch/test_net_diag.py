from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    
    page.on("console", lambda msg: print(f"CONSOLE [{msg.type}]: {msg.text}"))
    page.on("requestfailed", lambda req: print(f"REQ FAILED: {req.url} -> {req.failure}"))
    page.on("response", lambda res: print(f"RESP {res.status}: {res.url}") if res.status >= 400 else None)
    
    print("Navigating...")
    page.goto('https://familyinfocenter.brighthorizons.com/home', wait_until='domcontentloaded')
    page.wait_for_timeout(2000)
    
    btn = page.locator("button:has-text('Log In'), a:has-text('Log In')").first
    if btn.count() > 0:
        btn.click(force=True)
        page.wait_for_timeout(3000)
        
    print("On Auth0 URL:", page.url)
    page.wait_for_timeout(5000)
