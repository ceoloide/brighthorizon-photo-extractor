# Soft Handoff Report — Key Audit Area 1: Manual Substep Stepping Enforcement

## 1. Observation
- `backend/scraper_engine.py:260-266`: `wait_for_manual_step()` executes `self._step_event.clear()` followed by `self._step_event.wait(timeout=600)`. The return value of `.wait()` is ignored.
- `backend/scraper_engine.py:299`: `self.wait_for_manual_step("SSO form loaded. Click Next to type email.", 2, update_progress_cb)` occurs immediately before `username_inp.type(self.email, delay=50)` (line 307).
- `backend/scraper_engine.py:311`: `self.wait_for_manual_step("Email typed into input field. Click Next to submit email & run security challenge.", 2, update_progress_cb)` occurs immediately before `cont_btn.click(force=True)` / `Enter` (lines 313-317).
- `backend/scraper_engine.py:326`: `self.wait_for_manual_step(f"Security challenge verification (attempt {attempt+1}). Click Next to solve Cloudflare Turnstile.", 2, update_progress_cb)` occurs inside the attempt loop before solving Turnstile (lines 328-338).
- `backend/scraper_engine.py:346`: `self.wait_for_manual_step("Password field ready. Click Next to submit password.", 2, update_progress_cb)` occurs immediately before `pwd_inp.fill(self.password)` (line 354).
- `backend/scraper_engine.py:75`: `self._manual_step_mode: bool = options.get("manual_step_mode", False)` is initialized, but never checked inside `wait_for_manual_step()` or `perform_login()`.
- `backend/server.py:241-258`: Endpoint `POST /api/auth/next-step` calls `job.advance_step()`, setting `self._step_event.set()`.

## 2. Logic Chain
1. Substep pause placement in `perform_login()` strictly precedes each action (typing email, submitting email, solving turnstile, submitting password).
2. However, `self._step_event.wait(timeout=600)` returns `False` on timeout. Because the return value is unhandled and no exception is raised, execution falls through after 600 seconds and proceeds with the automated action anyway. Thus, an automated thread **can advance** without an explicit `POST /api/auth/next-step` event if 10 minutes pass.
3. Furthermore, `wait_for_manual_step()` is called unconditionally during `perform_login()`, ignoring `self._manual_step_mode`. This forces automated jobs without manual UI interaction to hit the 600-second timeout delays unless `_manual_step_mode` checking is implemented or `next-step` is signaled.
4. `self._step_event.clear()` inside `wait_for_manual_step()` creates a race condition if `POST /api/auth/next-step` is called before `_step_event.clear()` finishes executing, leading to missed signals.

## 3. Caveats
- Tested purely via code analysis and static code tracing.
- Did not run interactive live browser sessions against Auth0 during this audit turn.
- Did not inspect Turnstile solve timing details in depth (which is covered under Key Audit Area 2 / Explorer 2).

## 4. Conclusion
Key Audit Area 1 Verification Status: **FAIL / PARTIAL COMPLIANCE**
- Call placement before typing email, submitting email/Turnstile, and submitting password: **PASS**
- Strict enforcement (no auto-advance without signal): **FAIL** (600s timeout auto-advances; missing `_manual_step_mode` flag check; missing page liveness checks during pause).

## 5. Verification Method
1. Read `backend/scraper_engine.py` lines 260-360 and `backend/server.py` lines 241-258.
2. Verify line 266: `self._step_event.wait(timeout=600)` return value is unassigned.
3. Run `pytest backend/tests/` to verify baseline test execution.

## 6. Remaining Work
- If remediation is desired, update `wait_for_manual_step()` to check `if not self._manual_step_mode: return`, raise a `TimeoutError` or retry loop if `.wait()` returns `False`, and check `self._active_page.is_closed()`.
