# Formal Forensic Audit Report: Stepper, Turnstile Verification, & Session Persistence

**Target Repository**: `/home/antigravity/GitHub/brighthorizon-photo-extractor`  
**Auditor**: Forensic Integrity Auditor (`teamwork_preview_auditor_stepper`)  
**Audit Target**: Findings reported in `.agents/orchestrator_stepper_audit/audit_report.md`  
**Inspected Source Files**: `backend/scraper_engine.py`, `backend/server.py`  
**Date**: 2026-07-29  
**Formal Audit Verdict**: ❌ **INTEGRITY VIOLATION DETECTED** (Truthful & Authentic Findings Confirmed)

---

## Executive Summary

An independent, adversarial forensic audit was conducted on `backend/scraper_engine.py` and `backend/server.py` to independently verify the 4 core findings documented in `.agents/orchestrator_stepper_audit/audit_report.md`:
1. **600s Timeout Auto-Advance Vulnerability** in `wait_for_manual_step()`
2. **Missing Turnstile Token Extraction & Validation** (Blind 4s sleep)
3. **CRITICAL `/api/auth/verify-progress` Serialization Exception (`TypeError: Object of type ScraperJob is not JSON serializable`)**
4. **No-Op Session Cleanup Memory Leak** (`schedule_cleanup()` lacks `pop()`)

All 4 reported findings are **100% TRUTHFUL, AUTHENTIC, and VERIFIED BY EXACT CODE EVIDENCE**.

Furthermore, because these critical architectural defects and serialization bugs are present in production endpoints (`/api/auth/verify-progress` and `wait_for_manual_step`), the work product fails basic runtime integrity and behavior standards. Under the Integrity Forensics framework, a failure in behavioral verification or runtime safety requires an immediate verdict of **INTEGRITY VIOLATION DETECTED**.

---

## Forensic Check 1: Audit Claim Empirical Verification

### Finding 1: 600s Timeout Auto-Advance Vulnerability
- **Audit Claim**: `wait_for_manual_step()` ignores the boolean return value of `self._step_event.wait(timeout=600)`, causing worker threads to automatically advance after 10 minutes without receiving an explicit `POST /api/auth/next-step` event.
- **Empirical Code Verification**: **CONFIRMED (TRUTHFUL)**
- **Code Evidence** (`backend/scraper_engine.py:260-266`):
  ```python
  260:     def wait_for_manual_step(self, step_name: str, step_idx: int, update_cb: Optional[Callable[[str, int], None]] = None):
  261:         """Pauses execution until user clicks Next in UI (10 min timeout)."""
  262:         if update_cb:
  263:             update_cb(step_name, step_idx)
  264:         self._step_event.clear()
  265:         self.log(f"Paused at step: '{step_name}'. Waiting for user to click Next in UI...")
  266:         self._step_event.wait(timeout=600)
  ```
- **Forensic Assessment**: Line 266 calls `self._step_event.wait(timeout=600)` without capturing its boolean return value. When 600 seconds elapse, `wait()` returns `False`, control falls through to line 267/next instruction, and the worker thread proceeds to perform automated actions (typing email, clicking submit, submitting password) without user consent or signal.

### Finding 2: Missing Turnstile Token Extraction & Blind Sleep
- **Audit Claim**: Turnstile solving performs a blind 4-second sleep without verifying whether `cf-turnstile-response` contains a valid token, and pauses during manual steps risk token expiration prior to submission.
- **Empirical Code Verification**: **CONFIRMED (TRUTHFUL)**
- **Code Evidence** (`backend/scraper_engine.py:326-338`):
  ```python
  326:                     self.wait_for_manual_step(f"Security challenge verification (attempt {attempt+1}). Click Next to solve Cloudflare Turnstile.", 2, update_progress_cb)
  327:                     turnstile_iframe_el = page.locator("iframe[src*='challenges.cloudflare.com']").first
  328:                     if turnstile_iframe_el.count() > 0 and turnstile_iframe_el.is_visible():
  329:                         try:
  330:                             box = turnstile_iframe_el.bounding_box()
  331:                             if box:
  332:                                 page.mouse.click(box['x'] + 30, box['y'] + (box['height'] / 2))
  333:                             else:
  334:                                 turnstile_iframe_el.click(force=True)
  335:                             page.wait_for_timeout(4000)
  336:                             if cont_btn.count() > 0 and cont_btn.is_visible():
  337:                                 cont_btn.click(force=True)
  ```
- **Forensic Assessment**: Lines 330-335 click the Turnstile iframe and execute `page.wait_for_timeout(4000)`. There is zero inspection of `input[name='cf-turnstile-response']` or token payload. Additionally, line 326 triggers `wait_for_manual_step` before solving attempt; if the user pauses for several minutes after a Turnstile challenge is solved, any generated Turnstile token will expire (110-300s lifetime), causing Auth0 form submission to fail.

### Finding 3: `/api/auth/verify-progress` ScraperJob Serialization TypeError (HTTP 500)
- **Audit Claim**: `/api/auth/verify-progress` returns `JSONResponse(content=current_state)` without stripping `state["job"]` (a `ScraperJob` object), causing Starlette to raise `TypeError: Object of type ScraperJob is not JSON serializable` and crashing polling requests with HTTP 500.
- **Empirical Code Verification**: **CONFIRMED (TRUTHFUL & CRITICAL)**
- **Code Evidence** (`backend/server.py:90-91, 180-185`):
  ```python
  90:         job = ScraperJob(tenant_storage, password, {})
  91:         state["job"] = job
  ...
  180:     current_state = _active_verifications.get(tenant_id)
  181:     if not current_state or current_state.get("status") in ["failed", "completed_reset"]:
  182:         current_state = _start_verification_thread(email, req.password, tenant_storage)
  183:         return JSONResponse(content=current_state)
  184:         
  185:     return JSONResponse(content=current_state)
  ```
- **Contrast Evidence** (`backend/server.py:150` in `/api/auth/verify-stream`):
  ```python
  150:             clean_state = {k: v for k, v in state.items() if k != "job"}
  151:             payload = json.dumps(clean_state)
  ```
- **Forensic Assessment**: While `/api/auth/verify-stream` explicitly strips `"job"` at line 150 before JSON serialization, `/api/auth/verify-progress` at lines 183 and 185 passes `current_state` directly to `JSONResponse`. Because `current_state["job"]` contains a complex Python object (`ScraperJob`), FastAPI/Starlette's `jsonable_encoder` throws a fatal `TypeError` on every progress request.

### Finding 4: No-Op `schedule_cleanup()` Session Cleanup Memory Leak
- **Audit Claim**: `schedule_cleanup()` in `backend/server.py` sleeps for 300 seconds but fails to evict session state (`_active_verifications.pop(...)`), leaving verification states and Base64 screenshots in memory indefinitely.
- **Empirical Code Verification**: **CONFIRMED (TRUTHFUL)**
- **Code Evidence** (`backend/server.py:121-124`):
  ```python
  121:         finally:
  122:             def schedule_cleanup():
  123:                 time.sleep(300) # Retain verification session state & live preview screenshot for 5 minutes
  124:             threading.Thread(target=schedule_cleanup, daemon=True).start()
  ```
- **Forensic Assessment**: The inner function `schedule_cleanup()` executes `time.sleep(300)` and immediately exits without performing any dictionary deletion or cleanup call (such as `_active_verifications.pop(tenant_id, None)`). All session verification states, including heavy Base64 live preview screenshots, leak in memory permanently.

---

## Forensic Check 2: Code Integrity & Anti-Cheating Analysis

| Forensic Check | Result | Observation & Proof |
|---|---|---|
| **Hardcoded Test Results** | **CLEAN** | No hardcoded PASS/FAIL strings or canned test outputs found in `scraper_engine.py` or `server.py`. |
| **Facade Implementations** | **VIOLATION (Defect/Facade)** | `schedule_cleanup()` is a structural facade — it defines a thread wrapper and sleep block to give the appearance of background memory management, but contains zero eviction logic. |
| **Fabricated Verification Artifacts** | **CLEAN** | No pre-populated logs or fabricated result files pre-exist in the workspace. |
| **Self-Certifying Tests** | **CLEAN** | Unit tests in `backend/tests/test_security.py` test actual security isolation and JWT handling. |
| **Execution Delegation** | **CLEAN** | Target deliverable uses Playwright and FastAPI directly. |

---

## Conclusion & Verdict

All four findings documented in `.agents/orchestrator_stepper_audit/audit_report.md` are **authentic, accurate, and substantiated by raw code evidence**. The presence of an unhandled `TypeError` in an active API endpoint (`/api/auth/verify-progress`) and an auto-advancing manual pause lock in `wait_for_manual_step()` represent critical operational flaws.

**Formal Audit Verdict**: ❌ **INTEGRITY VIOLATION DETECTED**
