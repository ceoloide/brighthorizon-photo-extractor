import sys
import time
from playwright.sync_api import sync_playwright

email = "taccani.massarelli@gmail.com"
password = "xxTJ8i.5J2KUkkK"

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
        time.sleep(3)
        
    print(f"[Diag] SSO URL: {page.url}")
    
    # Dismiss banner
    page.evaluate("""() => {
        let btns = Array.from(document.querySelectorAll('button, a, div'));
        for (let b of btns) {
            if (b.textContent.trim() === '×' || b.getAttribute('aria-label') === 'Close') {
                b.click();
            }
        }
    }""")
    time.sleep(1)
    
    username_inp = page.locator("input[name='username']").first
    username_inp.wait_for(state="visible", timeout=10000)
    print("[Diag] Typing email...")
    username_inp.fill(email)
    
    # Click primary submit button via JS click or force click
    cont_btn = page.locator("button[type='submit']:not(.ulp-hidden-form-submit-button)").first
    print(f"[Diag] Force clicking Continue button...")
    cont_btn.click(force=True)
    time.sleep(4)
    
    print(f"[Diag] Post-Continue URL: {page.url}")
    
    pwd_inp = page.locator("input[name='password']:not(.hide)").first
    pwd_inp.wait_for(state="visible", timeout=10000)
    print("[Diag] Password field visible! Typing password...")
    pwd_inp.fill(password)
    
    login_btn = page.locator("button[type='submit']:not(.ulp-hidden-form-submit-button)").first
    login_btn.click(force=True)
    
    page.wait_for_load_state("networkidle", timeout=30000)
    time.sleep(5)
    
    print(f"[Diag] Final Post-Login URL: {page.url}")
    print(f"[Diag] Final Title: {page.title()}")
    
    h1s = [el.inner_text().strip() for el in page.locator("h1, h2, h3").all() if el.inner_text().strip()]
    print(f"[Diag] Final page headings: {h1s}")
    
    browser.close()
