import sys
import time
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
    )
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
    page = context.new_page()
    page.goto("https://familyinfocenter.brighthorizons.com/home", wait_until="domcontentloaded")
    time.sleep(3)
    
    btn = page.locator("button:has-text('Log In'), a:has-text('Log In')").first
    if btn.count() > 0 and btn.is_visible():
        btn.click()
        time.sleep(4)
        
    print(f"[Dump] SSO URL: {page.url}")
    with open("scratch/auth0.html", "w") as f:
        f.write(page.content())
    print("[Dump] Saved HTML to scratch/auth0.html")
    browser.close()
