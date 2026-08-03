# Handoff Report: Requirement R2 Turnstile Fast-Path & Auth0 Credential Entry

## 1. Observation
- **Target Files**: `backend/scraper_engine.py:395-515` (`solve_and_wait_turnstile`), `backend/scraper_engine.py:610-655` (`perform_login`).
- **Observed Behavior**: `solve_and_wait_turnstile` stalls for **50 seconds** on every login flow when Turnstile is absent (`challenge_present=False`).
- **Defective Condition (`backend/scraper_engine.py:415-437`)**:
  ```python
  token_info = page.evaluate("""() => {
      const inputs = document.querySelectorAll("input[name='cf-turnstile-response'], input[name='g-recaptcha-response']");
      return { count: inputs.length, populated: populated };
  }""")
  has_turnstile_input = token_info.get("count", 0) > 0
  ...
  if not has_turnstile_input and not has_cf_iframe:
      return True
  ```
  Auth0 Universal Login template renders `<input type="hidden" name="cf-turnstile-response">` statically in HTML. Thus `has_turnstile_input` evaluates to `True` regardless of whether Turnstile is active. The fast-path check `not has_turnstile_input and not has_cf_iframe` evaluates to `False and not has_cf_iframe` -> `False` every single time.
- **Resulting Loop**: `solve_and_wait_turnstile` enters a 50s polling loop, repeating 200 times before exiting at max timeout.

## 2. Logic Chain
1. Auth0 templates include static hidden inputs (`cf-turnstile-response`), causing `has_turnstile_input` to be `True`.
2. `solve_and_wait_turnstile` uses `has_turnstile_input` as a required gate for fast-path return (`not has_turnstile_input and not has_cf_iframe`).
3. Since `has_turnstile_input` is always `True`, the fast-path condition is never satisfied when Turnstile is absent (`has_cf_iframe == False`).
4. The worker thread blocks for `max_wait_sec = 50` seconds on every login, causing extreme latency and UX stalls.
5. Re-architecting `solve_and_wait_turnstile` to use a 1.5s grace period checking dynamic Cloudflare iframe presence (`challenges.cloudflare.com`) and challenge text (`"verify you are human"`) allows an instant fast-path exit when `challenge_present=False`.

## 3. Caveats
- Network latency or slow JS execution on heavily loaded client hardware might delay Cloudflare iframe insertion past 1.5 seconds. A 1.5s grace period strikes an optimal balance between fast-path response and challenge detection safety.
- In two-step Auth0 login flows (identifier-first), username input and password input appear on separate page states (`auth0_username` vs `auth0_password`). The fast-path logic supports both single-step unified login and two-step flows.

## 4. Conclusion
The 50s stall on Turnstile challenge absence is caused by relying on static hidden DOM inputs rather than active challenge indicators. The proposed zero-delay fast-path fix reduces login latency from 50+ seconds to under 2 seconds when Turnstile is absent, while maintaining full challenge solving capabilities when Turnstile is present.

## 5. Verification Method
1. **Source Inspection**: Inspect `backend/scraper_engine.py` to confirm the fast-path update to `solve_and_wait_turnstile` and `perform_login`.
2. **Log Verification**: Run login test (`pytest backend/tests/`) or auth verification. Check logs for:
   `[Turnstile] ⚡ Fast-Path: No active Cloudflare challenge frame or widget detected after 1.5s (challenge_present=False). Proceeding immediately to Auth0 credential entry...`
3. **Timing Audit**: Measure time elapsed between navigating to `/okta/login` and typing email address. Total pre-fill delay should decrease from 50s to ~1.5s.
