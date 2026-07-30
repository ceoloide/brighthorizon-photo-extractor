# Key Audit Area 3: Session & Live Preview Persistence Analysis

## Executive Summary

- **Audit Target**: `backend/server.py` and `backend/scraper_engine.py` in `/home/antigravity/GitHub/brighthorizon-photo-extractor`.
- **Audit Focus**: Session cleanup, session timeout handlers, background cleanup loops, live preview screenshot paths, job references, object lifecycles, and edge case race conditions.
- **Overall Status**: **PARTIAL PASS / FAIL ON API SERIALIZATION**
  - **Live Preview & Job Data Retention**: **PASS** (Live preview screenshots and job references/logs remain in memory after session completion or client disconnect, allowing UI state access).
  - **Session Cleanup Execution**: **FAIL / INCOMPLETE** (`schedule_cleanup()` sleeps for 300s but performs no dictionary deletion or memory cleanup).
  - **API Endpoint Robustness**: **FAIL** (`/api/auth/verify-progress` raises `TypeError: Object of type ScraperJob is not JSON serializable` because it fails to filter out the `job` reference from `current_state`).

---

## 1. Deep Code Inspection

### Session Storage & In-Memory Data Structures
`backend/server.py` maintains three main global dictionaries to manage session state, extraction jobs, and MFA rate limiting:
1. `_active_verifications: Dict[str, Dict[str, Any]] = {}` (Line 74) — Maps `tenant_id` to verification session state (`status`, `step`, `step_index`, `screenshot`, `children`, `error`, `timestamp`, and `job`).
2. `_active_jobs: Dict[str, ScraperJob] = {}` (Line 31) — Maps `tenant_id` to active `ScraperJob` instances running extraction tasks.
3. `_mfa_attempts: Dict[str, int] = {}` (Line 187) — Maps `tenant_id` to MFA attempt counts.

### Live Preview Screenshot Path & Generation
- Live preview screenshots are **not saved to disk**. They exist entirely as in-memory Base64-encoded JPEG strings (`data:image/jpeg;base64,...`).
- **Generation Source** (`backend/scraper_engine.py`, lines 32-39):
  ```python
  def capture_compressed_b64_frame(page: Page) -> Optional[str]:
      """Captures a lightweight JPEG screenshot (quality=40) encoded in Base64 data URI for live preview streaming."""
      try:
          img_bytes = page.screenshot(type="jpeg", quality=40)
          import base64
          return f"data:image/jpeg;base64,{base64.b64encode(img_bytes).decode('utf-8')}"
      except Exception:
          return None
  ```
- **Storage in Verification State** (`backend/server.py`, lines 100-101):
  ```python
  if p.get("screenshot"):
      state["screenshot"] = p.get("screenshot")
  ```

---

## 2. Verification of Session Timeout & Retention

### Does Session Timeout Cleanup Retain Live Preview Screenshots and Job References?
- **YES (Data Retention Verified)**:
  - When `run_verification()` completes (either with `"success"` or `"failed"`), the `finally` block spawns a daemon thread running `schedule_cleanup()` (`server.py`, lines 122-124).
  - Because `schedule_cleanup()` does not remove `_active_verifications[tenant_id]`, `state["screenshot"]` (the last captured Base64 frame) and `state["job"]` remain in memory inside `_active_verifications`.
  - Reconnecting to `/api/auth/verify-stream` or calling `/api/auth/verify-progress` returns the retained `state["screenshot"]` and completion state even after the browser context closes or the user disconnects.
  - Similarly, extraction jobs in `_active_jobs[tenant_id]` retain their status (`state`, `files_downloaded`, `logs`, `error`) indefinitely after completion.

### Static Payload vs. Interactive Session Lifecycle
- **Static Payload Access**: The live preview image (Base64 JPEG) and job status logs remain readable by the frontend indefinitely.
- **Interactive Action Lifecycle**:
  - `verify_credentials()` closes the Playwright `BrowserContext` in its `finally` block (`scraper_engine.py`, line 513).
  - Once closed, calling interactive endpoints like `/api/auth/interact-preview` (`job.click_preview`) will safely bypass execution via `if hasattr(self, "_active_page") and self._active_page and not self._active_page.is_closed():` without crashing, but clicks will no longer take effect.

---

## 3. Dictionary Deletions, File Unlinks & Object Lifecycles

### Dictionary Lifecycles & Purging Analysis

| Dictionary | Addition Trigger | Deletion / Purge Trigger | Cleanup Behavior | Bug / Deficiency |
| :--- | :--- | :--- | :--- | :--- |
| `_active_verifications` | `_start_verification_thread()` (Line 87) | **NEVER** | No dictionary `pop` or `del` exists in `server.py` | Memory leak; states persist indefinitely |
| `_active_jobs` | `start_extraction()` (Line 341) | `/api/auth/delete-account` (Line 307) | Removed only when tenant account is deleted | Retained forever post-completion |
| `_mfa_attempts` | `submit_mfa_code()` (Line 214) | `submit_mfa_code()` on success (Line 219) | Removed on successful MFA verification | Abandoned MFA attempts leak in memory |

### Image / File Unlink Operations
- **Live Preview Screenshots**: Purely in-memory strings (`data:image/jpeg;base64,...`). No file creation, no disk unlinks required or attempted.
- **Media Assets & User Data**: Stored under `/data/tenants/{tenant_id}/`. Disk unlinking occurs strictly during account deletion via `tenant.purge_all_data()` (`database.py`, lines 30-37), which calls `shutil.rmtree(self.tenant_dir)`.

---

## 4. Edge Cases & Race Condition Identification

### 1. CRITICAL BUG: `JSONResponse` Serialization Error in `/api/auth/verify-progress`
- **Location**: `backend/server.py`, lines 183 & 185:
  ```python
  @app.post("/api/auth/verify-progress")
  def verify_progress(req: LoginRequest):
      ...
      current_state = _active_verifications.get(tenant_id)
      if not current_state or current_state.get("status") in ["failed", "completed_reset"]:
          current_state = _start_verification_thread(email, req.password, tenant_storage)
          return JSONResponse(content=current_state)
          
      return JSONResponse(content=current_state)
  ```
- **Issue**: Line 91 inserts `state["job"] = job` (an instance of `ScraperJob`). When `JSONResponse(content=current_state)` is executed, Starlette attempts to serialize the `ScraperJob` instance using Python's standard `json.dumps()`. This fails with:
  `TypeError: Object of type ScraperJob is not JSON serializable`
- **Contrast**: `/api/auth/verify-stream` correctly sanitizes state on line 150:
  ```python
  clean_state = {k: v for k, v in state.items() if k != "job"}
  ```
- **Impact**: Any client polling `/api/auth/verify-progress` receives HTTP 500 Internal Server Error as soon as `job` is assigned to `state`.

### 2. INCOMPLETE CLEANUP: No-Op `schedule_cleanup()` Function
- **Location**: `backend/server.py`, lines 122-124:
  ```python
  finally:
      def schedule_cleanup():
          time.sleep(300) # Retain verification session state & live preview screenshot for 5 minutes
      threading.Thread(target=schedule_cleanup, daemon=True).start()
  ```
- **Issue**: `schedule_cleanup()` sleeps for 300 seconds and then exits without performing any cleanup. It does not execute `_active_verifications.pop(tenant_id, None)` nor does it clear `state["screenshot"]`.
- **Impact**: Memory leak over time as `_active_verifications` grows unbounded across multiple user logins.

### 3. RACE CONDITION: Concurrent Login Requests for the Same Tenant
- **Location**: `backend/server.py`, lines 140-142 & 180-182.
- **Issue**: If two login/verification requests hit the API simultaneously before `_active_verifications[tenant_id]` is set by the first request, both threads call `_start_verification_thread()`. Both attempt to launch Playwright Chromium instances using the same `user_data_dir` (`/data/tenants/{tenant_id}/user_data`).
- **Impact**: Chromium throws a Singleton lock error (`TargetClosedError`), causing one or both verification sessions to crash.

### 4. RACE CONDITION: Preview Interaction Post-Browser Context Close
- **Location**: `backend/server.py`, lines 223-239 (`interact_preview`).
- **Issue**: If a user sends a click request right after `verify_credentials` completes or times out, the browser page is closed (`_active_page.is_closed() == True`).
- **Impact**: The endpoint returns `{"status": "success", "message": "Click replicated..."}` even though the browser session is closed and no click occurred.

---

## 5. Summary Matrix & Verification Status

| Sub-Area | Verification Criteria | Status | Code Reference |
| :--- | :--- | :--- | :--- |
| **Data Retention** | Live preview screenshots & job status persist after disconnect/timeout | **PASS** | `server.py`: Lines 100-101, 122-124 |
| **Preview Path** | Screenshots captured as Base64 in-memory data URIs | **PASS** | `scraper_engine.py`: Lines 32-39 |
| **API Endpoint** | `/api/auth/verify-progress` returns valid JSON response | **FAIL** | `server.py`: Lines 183, 185 (Fails to filter `job`) |
| **Session Cleanup** | `schedule_cleanup()` purges expired verification states after 5 minutes | **FAIL** | `server.py`: Lines 122-124 (No-op sleep) |
| **MFA Rate Limit Purge** | Unused/abandoned MFA attempt entries are cleaned up | **FAIL** | `server.py`: Lines 214-219 (`_mfa_attempts` leaks) |

---

## 6. Verification Method

To independently verify these findings:

1. **Verify `verify-progress` JSON Serialization Bug**:
   Inspect `server.py` line 183 & 185 vs line 150:
   ```bash
   grep -n "JSONResponse" backend/server.py
   ```
   Note that line 150 uses `clean_state = {k: v for k, v in state.items() if k != "job"}`, whereas lines 183 and 185 pass `current_state` directly containing `state["job"]`.

2. **Verify No-Op `schedule_cleanup()`**:
   Inspect `server.py` lines 122-124:
   ```bash
   sed -n '120,126p' backend/server.py
   ```
   Observe that `schedule_cleanup()` contains only `time.sleep(300)` and no `pop` or `del` calls.

3. **Verify Screenshot Storage in Memory**:
   Inspect `scraper_engine.py` lines 32-39 & `server.py` lines 100-101:
   ```bash
   grep -n "capture_compressed_b64_frame" backend/scraper_engine.py
   ```
