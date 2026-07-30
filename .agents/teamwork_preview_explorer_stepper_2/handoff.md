# Soft Handoff Report — Key Audit Area 2: Turnstile Timing

## 1. Observation
- Target file inspected: `backend/scraper_engine.py` (lines 111-131, 301-342, 435-470).
- FlareSolverr pre-clearance queries external solver at `backend/scraper_engine.py:118`.
- `perform_login()` email typing occurs at `backend/scraper_engine.py:307`.
- Email submission pause: `self.wait_for_manual_step(...)` at line 311.
- Turnstile iframe locator: `iframe[src*='challenges.cloudflare.com']` at line 327.
- Turnstile manual step pause: line 326.
- Mouse coordinate click: `page.mouse.click(box['x'] + 30, box['y'] + (box['height'] / 2))` at line 332.
- Post-click timeout: `page.wait_for_timeout(4000)` at line 335.

## 2. Logic Chain
- Step 1: `perform_login()` enters email and calls `wait_for_manual_step` before submitting email (`cont_btn.click()`).
- Step 2: After submitting email, the loop at line 323 checks for password field. If not present, it pauses via `wait_for_manual_step` for security challenge.
- Step 3: This confirms Turnstile solving is NOT prematurely invoked before email typing. (Passes Task 2 sequencing requirement).
- Step 4: However, mouse click execution is followed by a blind 4-second timeout (`page.wait_for_timeout(4000)`) without checking if `input[name='cf-turnstile-response']` or `div[data-captcha-sitekey] input` contains a valid token string.
- Step 5: Furthermore, `wait_for_manual_step` can pause up to 600 seconds. Turnstile tokens expire after ~110-300 seconds. If a user delays clicking "Next", the token will expire before `cont_btn` click.

## 3. Caveats
- Tested on standard Auth0 / Cloudflare Turnstile DOM structure (`scratch/auth0.html` and standard Cloudflare widgets).
- Actual live Cloudflare challenge behavior depends on browser fingerprint stealth and IP reputation.

## 4. Conclusion
- **Key Audit Area 2 Verification Status:** ❌ **FAIL**
- **Summary:** Sequencing relative to email typing is correct, but the implementation lacks Turnstile token extraction/validation guards, relies on a hardcoded 4s sleep, is vulnerable to token expiration during manual step pauses, and has a race condition if the password field appears asynchronously.

## 5. Verification Method
- Code inspection of `backend/scraper_engine.py:301-345`.
- Verify token input status using Playwright evaluation on Auth0 form:
  `page.locator("input[name='cf-turnstile-response']").evaluate("(el) => el.value")`.
- Invalidation condition: Turnstile token input remains empty when `cont_btn` is clicked at line 337.

## 6. Remaining Work / Recommendations for Implementer
- Replace fixed 4000ms sleep with active token polling (`input[name='cf-turnstile-response']`).
- Add token freshness/expiration check before submitting forms when paused in manual step mode.
- Re-check password input visibility immediately after `wait_for_manual_step()` unblocks.
