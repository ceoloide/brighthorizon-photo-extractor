import requests
import json
from playwright.sync_api import sync_playwright

FLARESOLVERR_URL = "http://192.168.1.176:8191/v1"

# Step 1: Create a FlareSolverr session
print("Creating FlareSolverr session...")
session_resp = requests.post(FLARESOLVERR_URL, json={
    "cmd": "sessions.create"
}, timeout=30).json()

session_id = session_resp.get("session")
print("FlareSolverr session created:", session_id)

try:
    # Step 2: Query okta/login via FlareSolverr session
    print("Navigating to okta/login via FlareSolverr session...")
    r1 = requests.post(FLARESOLVERR_URL, json={
        "cmd": "request.get",
        "url": "https://familyinfocenter.brighthorizons.com/okta/login",
        "session": session_id,
        "maxTimeout": 60000
    }, timeout=65).json()
    
    cookies = r1.get("solution", {}).get("cookies", [])
    user_agent = r1.get("solution", {}).get("userAgent")
    print(f"Session cookies ({len(cookies)}):", [c["name"] for c in cookies])
    print("User-Agent:", user_agent)
    
    # Step 3: Now open Playwright with the FlareSolverr session cookies & User-Agent
    with sync_playwright() as p:
        args = ["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage"]
        context = p.chromium.launch_persistent_context(
            "/tmp/fs_session_dir",
            headless=True,
            args=args,
            ignore_default_args=["--enable-automation"],
            user_agent=user_agent
        )
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
            
        page = context.new_page()
        page.goto("https://familyinfocenter.brighthorizons.com/okta/login", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        
        login_btn = page.locator("button:has-text('Log In'), a:has-text('Log In')").first
        print("Clicking Log In button in Playwright...")
        login_btn.click(force=True)
        page.wait_for_timeout(3000)
        print("URL on Auth0:", page.url)
        
        username_inp = page.locator("input[name='username']").first
        username_inp.wait_for(state="visible", timeout=25000)
        print("Filling email...")
        username_inp.fill("taccani.massarelli@gmail.com")
        page.wait_for_timeout(1000)
        
        cont_btn = page.locator("button._button-login-id, button[type='submit']:not(.ulp-hidden-form-submit-button)").first
        print("Clicking Continue button...")
        cont_btn.click(force=True)
        page.wait_for_timeout(4000)
        
        pwd_inp = page.locator("input[name='password']:not(.hide), input[id='password']").first
        print("Password input count:", pwd_inp.count(), "is_visible:", pwd_inp.first.is_visible() if pwd_inp.count() > 0 else False)
        print("Errors:", [e.inner_text() for e in page.locator(".ulp-input-error-message, .alert, .error, p.error").all()])

finally:
    if session_id:
        requests.post(FLARESOLVERR_URL, json={"cmd": "sessions.destroy", "session": session_id})
