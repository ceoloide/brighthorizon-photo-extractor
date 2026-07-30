import os, sys, time, json
from playwright.sync_api import sync_playwright

email = "taccani.massarelli@gmail.com"
user_data_dir = f"/data/tenants/{email}/user_data"
state_file = os.path.join(user_data_dir, "storage_state.json")

print(f"Checking storage_state.json at {state_file}...")
if not os.path.exists(state_file):
    print("Storage state file does not exist!")
    sys.exit(1)

with open(state_file, "r") as f:
    state_data = json.load(f)

print(f"Loaded {len(state_data.get('cookies', []))} cookies from storage state.")

with sync_playwright() as p:
    print("Launching Playwright Chromium with imported user cookies...")
    browser = p.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
    context = browser.new_context(viewport={"width": 1280, "height": 720})
    
    # Add cookies directly to context
    context.add_cookies(state_data["cookies"])
    
    page = context.new_page()
    print("Navigating to https://familyinfocenter.brighthorizons.com/home...")
    page.goto("https://familyinfocenter.brighthorizons.com/home", wait_until="domcontentloaded")
    page.wait_for_timeout(4000)
    
    print(f"Current Portal URL: {page.url}")
    body_text = page.locator("body").inner_text()
    
    page.screenshot(path="scratch/portal_cookie_test.png")
    
    if "Byron" in body_text or "Actions" in body_text:
        print("🎉 SUCCESS! Portal page loaded cleanly! Byron / Actions buttons discovered!")
    elif "Log In" in body_text or "okta/login" in page.url:
        print("Redirected to login. (Session cookies need Auth0 token refresh)")
    else:
        print("Portal snippet:")
        print(body_text[:500])

    browser.close()
