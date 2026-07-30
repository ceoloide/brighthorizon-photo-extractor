import os, sys, time, requests
from playwright.sync_api import sync_playwright

email = "taccani.massarelli@gmail.com"
password = "xxTJ8i.5J2KUkkK"

# First, let's query FlareSolverr for clearance cookies on bhloginsso
print("1. Querying FlareSolverr for Turnstile clearance cookies...")
fs_url = "http://192.168.1.176:8191/v1"
fs_payload = {
    "cmd": "request.get",
    "url": "https://bhloginsso.brighthorizons.com/u/login/identifier",
    "maxTimeout": 60000
}

cookies = []
user_agent = None

try:
    r = requests.post(fs_url, json=fs_payload, timeout=70)
    if r.status_code == 200:
        data = r.json()
        sol = data.get("solution", {})
        cookies = sol.get("cookies", [])
        user_agent = sol.get("userAgent")
        print(f"✓ FlareSolverr returned {len(cookies)} cookies! UA: {user_agent}")
except Exception as e:
    print("FlareSolverr error:", e)

user_data_dir = "/tmp/test_user_data_stealth"
os.makedirs(user_data_dir, exist_ok=True)

with sync_playwright() as p:
    print("2. Launching Playwright Chromium headful with stealth...")
    context = p.chromium.launch_persistent_context(
        user_data_dir,
        headless=False,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--disable-dev-shm-usage", "--window-size=1280,720"],
        ignore_default_args=["--enable-automation"],
        user_agent=user_agent
    )
    
    # Inject FlareSolverr clearance cookies if available
    if cookies:
        pw_cookies = []
        for c in cookies:
            cookie_dict = {
                "name": c["name"],
                "value": c["value"],
                "domain": c["domain"] if c.get("domain") else ".brighthorizons.com",
                "path": c.get("path", "/"),
            }
            pw_cookies.append(cookie_dict)
        try:
            context.add_cookies(pw_cookies)
            print("Injected FlareSolverr cookies into context!")
        except Exception as e:
            print("Cookie injection error:", e)

    page = context.pages[0] if context.pages else context.new_page()

    # Try applying stealth
    try:
        from playwright_stealth import stealth_sync
        stealth_sync(page)
        print("Applied playwright-stealth to page!")
    except Exception as e:
        print("Stealth import error:", e)

    print("3. Navigating to familyinfocenter.brighthorizons.com/okta/login...")
    page.goto("https://familyinfocenter.brighthorizons.com/okta/login", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)

    login_btn = page.locator("button:has-text('Log In'), a:has-text('Log In')").first
    if login_btn.count() > 0 and login_btn.is_visible():
        print("Clicking Landing Page Log In button...")
        login_btn.click()
        page.wait_for_load_state("domcontentloaded")
        page.wait_for_timeout(3000)

    print("4. Inspecting SSO page Turnstile state...")
    for sec in range(15):
        body_text = page.locator("body").inner_text()
        body_lower = body_text.lower()
        if "success!" in body_lower or "success" in body_lower:
            print(f"🎉 YES! Turnstile SUCCESS detected after {sec+1} seconds!")
            page.screenshot(path="scratch/turnstile_success_verified.png")
            break
        elif "verify you are human" in body_lower:
            print(f"Turnstile state: 'Verify you are human' (sec {sec+1})")
        elif "verifying" in body_lower:
            print(f"Turnstile state: 'Verifying...' (sec {sec+1})")
            
        page.wait_for_timeout(1000)

    page.screenshot(path="scratch/stealth_turnstile_final.png")
    context.close()
