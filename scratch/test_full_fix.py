from playwright.sync_api import sync_playwright
import time

with sync_playwright() as p:
    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage"
    ]
    context = p.chromium.launch_persistent_context(
        "/tmp/full_fix_test_dir_5",
        headless=True,
        args=args,
        ignore_default_args=["--enable-automation"],
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
    )
    
    init_js = """
    Object.defineProperty(navigator, 'userAgentData', {
        get: () => ({
            brands: [
                { brand: 'Google Chrome', version: '125' },
                { brand: 'Chromium', version: '125' },
                { brand: 'Not=A?Brand', version: '24' }
            ],
            mobile: false,
            platform: 'macOS',
            getHighEntropyValues: async () => ({
                architecture: 'x86',
                bitness: '64',
                brands: [
                    { brand: 'Google Chrome', version: '125' },
                    { brand: 'Chromium', version: '125' },
                    { brand: 'Not=A?Brand', version: '24' }
                ],
                fullVersionList: [
                    { brand: 'Google Chrome', version: '125.0.6422.26' },
                    { brand: 'Chromium', version: '125.0.6422.26' },
                    { brand: 'Not=A?Brand', version: '24.0.0.0' }
                ],
                mobile: false,
                model: '',
                platform: 'macOS',
                platformVersion: '14.5.0',
                uaFullVersion: '125.0.6422.26'
            })
        })
    });
    """
    context.add_init_script(init_js)
    
    page = context.new_page()
    try:
        from playwright_stealth import Stealth
        Stealth().apply_stealth_sync(page)
    except Exception as e:
        print("Stealth notice:", e)
        
    print("Navigating to familyinfocenter.brighthorizons.com/home...")
    page.goto('https://familyinfocenter.brighthorizons.com/home', wait_until='domcontentloaded')
    
    print("Waiting for redirection or login elements...")
    start = time.time()
    while time.time() - start < 25:
        url_lower = page.url.lower()
        if "auth0" in url_lower or "bhloginsso" in url_lower:
            print("Redirected to Auth0 SSO:", page.url)
            break
            
        username_inp = page.locator("input[name='username'], input[id='username'], input[type='email']")
        if username_inp.count() > 0 and username_inp.first.is_visible():
            print("Auth0 username input found directly!")
            break
            
        login_btn = page.locator("button:has-text('Log In'), a:has-text('Log In'), button.btn-primary, a.btn-primary")
        if login_btn.count() > 0 and login_btn.first.is_visible():
            print("Clicking portal Log In button...")
            login_btn.first.click(force=True)
            page.wait_for_timeout(3000)
            break
            
        time.sleep(1)
        
    print("URL on Auth0 step:", page.url)
    username_inp = page.locator("input[name='username'], input[id='username'], input[type='email']").first
    username_inp.wait_for(state="visible", timeout=25000)
    print("Filling email...")
    username_inp.fill("taccani.massarelli@gmail.com")
    page.wait_for_timeout(500)
    
    cont_btn = page.locator("button._button-login-id, button[type='submit']:not(.ulp-hidden-form-submit-button)").first
    if cont_btn.count() > 0 and cont_btn.is_visible():
        print("Clicking Continue button...")
        cont_btn.click(force=True)
    else:
        username_inp.press("Enter")
        
    pwd_inp = page.locator("input[name='password']:not(.hide), input[id='password']").first
    pwd_inp.wait_for(state="visible", timeout=25000)
    print("Password input visible successfully!")
    print("Filling password...")
    pwd_inp.fill("xxTJ8i.5J2KUkkK")
    page.wait_for_timeout(500)
    
    login_btn = page.locator("button._button-login-id, button[type='submit']:not(.ulp-hidden-form-submit-button)").first
    if login_btn.count() > 0 and login_btn.is_visible():
        print("Clicking Log In button...")
        login_btn.click(force=True)
    else:
        pwd_inp.press("Enter")
        
    page.wait_for_timeout(5000)
    print("Post login URL:", page.url)
    actions = page.locator("span:has-text('Actions')")
    print("Actions span count:", actions.count())
