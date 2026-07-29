import sys
import time
import requests
from playwright.sync_api import sync_playwright

email = "taccani.massarelli@gmail.com"
password = "xxTJ8i.5J2KUkkK"
FLARESOLVERR_URL = "http://192.168.1.176:8191/v1"

def get_flaresolverr_cookies(url):
    print(f"[FlareSolverr] Resolving challenge for {url}...")
    try:
        resp = requests.post(FLARESOLVERR_URL, json={"cmd": "request.get", "url": url, "maxTimeout": 60000}, timeout=70)
        if resp.status_code == 200:
            sol = resp.json().get("solution", {})
            return sol.get("cookies", []), sol.get("userAgent")
    except Exception as e:
        print(f"[FlareSolverr Error]: {e}")
    return [], None

cookies, user_agent = get_flaresolverr_cookies("https://familyinfocenter.brighthorizons.com/home")

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
    )
    
    ua = user_agent or "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    context = browser.new_context(user_agent=ua)
    
    if cookies:
        formatted = []
        for c in cookies:
            formatted.append({
                "name": c["name"],
                "value": c["value"],
                "domain": c["domain"],
                "path": c.get("path", "/"),
                "secure": c.get("secure", False)
            })
        context.add_cookies(formatted)
        print(f"[Playwright] Injected {len(formatted)} FlareSolverr clearance cookies.")
        
    page = context.new_page()
    page.goto("https://familyinfocenter.brighthorizons.com/home", wait_until="domcontentloaded")
    time.sleep(3)
    
    btn = page.locator("button:has-text('Log In'), a:has-text('Log In')").first
    if btn.count() > 0 and btn.is_visible():
        btn.click()
        time.sleep(3)
        
    print(f"[Playwright] SSO Page URL: {page.url}")
    
    username_inp = page.locator("input[name='username']").first
    username_inp.wait_for(state="visible", timeout=10000)
    username_inp.fill(email)
    
    cont_btn = page.locator("button._button-login-id, button[data-action-button-primary='true']").first
    cont_btn.click()
    time.sleep(4)
    
    print(f"[Playwright] Post-Continue URL: {page.url}")
    
    pwd_inp = page.locator("input[name='password']").first
    if pwd_inp.count() > 0 and pwd_inp.is_visible():
        print("[Playwright] Password field visible! Filling password...")
        pwd_inp.fill(password)
        login_btn = page.locator("button._button-login-id, button[data-action-button-primary='true']").first
        login_btn.click()
        time.sleep(5)
        
    print(f"[Playwright] Final URL: {page.url}")
    print(f"[Playwright] Final Title: {page.title()}")
    
    browser.close()
