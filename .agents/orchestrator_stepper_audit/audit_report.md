# Comprehensive Code Audit Report: Manual Stepper, Turnstile Verification Flow, and Session Persistence

**Target Repository**: `/home/antigravity/GitHub/brighthorizon-photo-extractor`  
**Audit Conducted By**: Project Orchestrator & Multi-Agent Exploration Team  
**Date**: 2026-07-29  
**Overall Verification Verdict**: ❌ **FAIL (Critical Bugs & Remediation Required)**

---

## Executive Summary

An in-depth adversarial code audit was conducted on the Bright Horizons Photo Extractor codebase, specifically focusing on the manual login stepper, Cloudflare Turnstile challenge solving timing, and session state persistence in `backend/scraper_engine.py` and `backend/server.py`.

While the sequential placement of manual step pauses strictly precedes automated actions (email typing, email submission, password submission), the overall verification **FAILS** due to four critical issues:
1. **Timeout Auto-Advance Vulnerability**: `wait_for_manual_step()` ignores the boolean return value of `self._step_event.wait(timeout=600)`, causing worker threads to automatically advance and execute login actions after 10 minutes without receiving an explicit `POST /api/auth/next-step` event.
2. **Turnstile Blind Sleep & Token Expiry**: Turnstile handling performs a blind 4-second sleep without verifying whether `cf-turnstile-response` contains a valid token. Pausing execution during manual steps risks Turnstile token expiration prior to submission.
3. **CRITICAL API Serialization Exception (HTTP 500)**: `/api/auth/verify-progress` in `backend/server.py` returns `JSONResponse(content=current_state)` without filtering out `state["job"]` (a `ScraperJob` object), causing Starlette to throw `TypeError: Object of type ScraperJob is not JSON serializable` and crashing progress polling.
4. **No-Op Session Cleanup Memory Leak**: `schedule_cleanup()` in `backend/server.py` performs a `time.sleep(300)` but executes no state eviction (`_active_verifications.pop(...)`), leaving verification states and screenshots in memory indefinitely.

---

## Audit Key Area 1: Manual Substep Stepping Enforcement

### Requirement
Verify that `perform_login()` in `backend/scraper_engine.py` strictly calls `wait_for_manual_step()` before typing email, before submitting email/Turnstile, and before submitting password. Ensure no automated thread advances without an explicit `POST /api/auth/next-step` event.

### Verification Status: ❌ **FAIL / PARTIAL PASS**

### Concrete Findings & Placement Analysis
- **Before Typing Email**: **PASS** (`backend/scraper_engine.py:299` calls `self.wait_for_manual_step("Waiting for user to initiate email entry...", 1)` before `username_inp.type(self.email)` at line 307).
- **Before Submitting Email / Turnstile**: **PASS** (`backend/scraper_engine.py:311` calls `wait_for_manual_step` before `cont_btn.click()` at line 315, and line 326 calls `wait_for_manual_step` before Turnstile solving attempts at lines 327-338).
- **Before Submitting Password**: **PASS** (`backend/scraper_engine.py:346` calls `wait_for_manual_step` before `pwd_inp.fill(self.password)` and `login_btn.click()` at lines 354-358).

### Critical Vulnerabilities & Race Conditions
1. **600-Second Timeout Auto-Advance Vulnerability**:
   ```python
   # backend/scraper_engine.py:260-266
   def wait_for_manual_step(self, step_name: str, step_idx: int, update_cb: Optional[Callable[[str, int], None]] = None):
       if update_cb:
           update_cb(step_name, step_idx)
       self._step_event.clear()
       self.log(f"Paused at step: '{step_name}'. Waiting for user to click Next in UI...")
       self._step_event.wait(timeout=600)  # Return value (False on timeout) is ignored!
   ```
   If the user does NOT click Next within 10 minutes, `self._step_event.wait(600)` returns `False`, but execution resumes unconditionally, executing automated actions without user interaction.
2. **Race Condition in Event Clearing**: If `POST /api/auth/next-step` arrives right before `self._step_event.clear()` is called, the signal is cleared and ignored, causing the worker thread to hang for 10 minutes.
3. **Liveness Check Deficit**: `wait_for_manual_step()` does not poll `page.is_closed()`. If the user closes the browser during a manual pause, the thread remains blocked for up to 600 seconds before throwing a `TargetClosedError`.

---

## Audit Key Area 2: Turnstile Timing & Token Handling

### Requirement
Verify that Turnstile solving logic is invoked ONLY after email typing is complete and `wait_for_manual_step` has been triggered.

### Verification Status: ❌ **FAIL**

### Concrete Findings & Timing Analysis
- **Step Sequencing**: **PASS**. In `backend/scraper_engine.py:307-327`, email typing completes at line 307, `wait_for_manual_step` pauses at line 311, `cont_btn` is clicked at line 315, `wait_for_manual_step` pauses for security challenge at line 326, and Turnstile iframe locator/click is executed at line 327.

### Critical Vulnerabilities & Race Conditions
1. **Missing Token Extraction & Verification**:
   ```python
   # backend/scraper_engine.py:330-337
   box = turnstile_iframe_el.bounding_box()
   if box:
       page.mouse.click(box['x'] + 30, box['y'] + (box['height'] / 2))
   else:
       turnstile_iframe_el.click(force=True)
   page.wait_for_timeout(4000) # Blind sleep!
   if cont_btn.count() > 0 and cont_btn.is_visible():
       cont_btn.click(force=True)
   ```
   The engine does not inspect `input[name='cf-turnstile-response']` or captcha token elements. It performs a mouse click and blindly waits 4 seconds. If an interactive challenge appears or network latency exceeds 4 seconds, `cont_btn` is clicked prematurely without a valid token.
2. **Token Expiration during Manual Step Pause**: Turnstile tokens expire within 110-300 seconds. If Turnstile resolves automatically or is solved early, and the user pauses at `wait_for_manual_step` (line 326) for longer than 2 minutes, submitting the form at line 337 results in an Auth0 `invalid_captcha` failure.
3. **Asynchronous Password Field Race**: Line 324 checks if `pwd_inp` is visible *before* calling `wait_for_manual_step`. If Auth0 advances to the password input asynchronously during the step pause, lines 327-334 still attempt mouse clicks on the coordinates of a lingering or hidden iframe overlay.

---

## Audit Key Area 3: Session & Live Preview Persistence

### Requirement
Verify that session timeout cleanup in `backend/server.py` retains live preview screenshots and job references.

### Verification Status: ❌ **FAIL (API Serialization Bug & No-Op Cleanup)**

### Concrete Findings & Persistence Analysis
- **Live Preview Data Retention**: **PASS**. Screenshots are captured as Base64 JPEG data URIs (`data:image/jpeg;base64,...`) via `capture_compressed_b64_frame()` in `backend/scraper_engine.py:32-39` and stored in `_active_verifications[tenant_id]["screenshot"]`. They remain accessible in memory post-completion.

### Critical Vulnerabilities & Race Conditions
1. **CRITICAL API Bug in `/api/auth/verify-progress` (HTTP 500 Exception)**:
   ```python
   # backend/server.py:183 & 185
   @app.post("/api/auth/verify-progress")
   def verify_progress(req: LoginRequest):
       ...
       current_state = _active_verifications.get(tenant_id)
       ...
       return JSONResponse(content=current_state)  # FAILS! Contains state["job"]
   ```
   `_start_verification_thread` assigns `state["job"] = job` (`ScraperJob` instance). Unlike `/api/auth/verify-stream` (which filters `clean_state = {k: v for k, v in state.items() if k != "job"}` at line 150), `/api/auth/verify-progress` returns `current_state` directly. Starlette throws `TypeError: Object of type ScraperJob is not JSON serializable`, producing an HTTP 500 Server Error on polling.
2. **No-Op `schedule_cleanup()` Memory Leak**:
   ```python
   # backend/server.py:122-124
   finally:
       def schedule_cleanup():
           time.sleep(300) # Retain verification session state & live preview screenshot for 5 minutes
       threading.Thread(target=schedule_cleanup, daemon=True).start()
   ```
   `schedule_cleanup()` sleeps for 300 seconds and exits without calling `_active_verifications.pop(tenant_id, None)`. Expired verification states and screenshots leak in memory indefinitely.

---

## Verification Matrix & Status Summary

| Area | Audit Item | Verification Status | Exact Code Reference |
|---|---|:---:|---|
| **Area 1** | Substep Call Before Email Typing | **PASS** | `backend/scraper_engine.py:299` |
| **Area 1** | Substep Call Before Email Submit | **PASS** | `backend/scraper_engine.py:311` |
| **Area 1** | Substep Call Before Password Submit | **PASS** | `backend/scraper_engine.py:346` |
| **Area 1** | Strict Signal Enforcement (No Auto-Advance) | **FAIL** | `backend/scraper_engine.py:266` (`wait()` timeout return ignored) |
| **Area 2** | Turnstile Sequencing (Post-Email Typing) | **PASS** | `backend/scraper_engine.py:307-327` |
| **Area 2** | Turnstile Token Extraction & Validation | **FAIL** | `backend/scraper_engine.py:330-337` (Blind sleep, no token check) |
| **Area 2** | Turnstile Token Expiry Window Handling | **FAIL** | `backend/scraper_engine.py:326` (10-min pause can expire token) |
| **Area 3** | Live Preview Screenshot Retention | **PASS** | `backend/server.py:100-101`, `scraper_engine.py:32-39` |
| **Area 3** | `/api/auth/verify-progress` JSON Serialization | **FAIL** | `backend/server.py:183,185` (`TypeError: ScraperJob not JSON serializable`) |
| **Area 3** | Session Timeout Cleanup Eviction | **FAIL** | `backend/server.py:122-124` (No-op `sleep(300)` without `.pop()`) |

---

## Required Remediation Actions

1. **Fix `wait_for_manual_step()` Timeout Enforcement**:
   - Check the return value of `self._step_event.wait(timeout=600)`. If `False`, raise a `TimeoutError("Manual step timed out waiting for user input")` or set status to `"failed"`.
   - Add periodic checks for `page.is_closed()` inside a short loop (e.g. `while not self._step_event.wait(timeout=1): if page.is_closed(): raise ...`).
2. **Fix `/api/auth/verify-progress` Serialization Error**:
   - In `backend/server.py:183,185`, filter out the `"job"` key before returning:
     `clean_state = {k: v for k, v in current_state.items() if k != "job"}`
     `return JSONResponse(content=clean_state)`
3. **Fix `schedule_cleanup()` State Eviction**:
   - Update `schedule_cleanup()` in `backend/server.py` to pop the tenant ID after sleeping:
     ```python
     def schedule_cleanup():
         time.sleep(300)
         _active_verifications.pop(tenant_id, None)
     ```
4. **Hardened Turnstile Verification**:
   - Check `input[name='cf-turnstile-response']` or `div[data-captcha-sitekey] input` for a non-empty string before proceeding to click `cont_btn`.
   - Replace fixed `page.wait_for_timeout(4000)` with a dynamic wait loop checking for token presence.
