from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    args = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage"
    ]
    context = p.chromium.launch_persistent_context(
        "/tmp/ua_data_test_dir_3",
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
    page.on("response", lambda res: print(f"RESP {res.status}: {res.url}") if "challenge-platform" in res.url else None)
    
    try:
        from playwright_stealth import Stealth
        Stealth().apply_stealth_sync(page)
    except Exception as e:
        print("Stealth notice:", e)
        
    print("1. Navigating to familyinfocenter.brighthorizons.com/home...")
    page.goto('https://familyinfocenter.brighthorizons.com/home', wait_until='domcontentloaded')
    page.wait_for_timeout(3000)
    print("URL 1:", page.url)
    
    login_btn = page.locator("button:has-text('Log In'), a:has-text('Log In')").first
    print("Clicking Log In button...")
    login_btn.click(force=True)
    page.wait_for_timeout(4000)
    print("URL 2 (Auth0):", page.url)
    
    username = page.locator("input[name='username']").first
    if username.count() > 0:
        print("Filling email...")
        username.fill('taccani.massarelli@gmail.com')
        page.wait_for_timeout(1000)
        
        cont = page.locator("button._button-login-id, button[type='submit']:not(.ulp-hidden-form-submit-button)").first
        print("Clicking continue button...")
        cont.click()
        page.wait_for_timeout(5000)
        print("URL 3 post email:", page.url)
        pwd = page.locator("input[name='password']")
        print("Password input count:", pwd.count(), "is_visible:", pwd.first.is_visible() if pwd.count() > 0 else False)
        print("Errors:", [e.inner_text() for e in page.locator(".ulp-input-error-message, .alert, .error, p.error").all()])
