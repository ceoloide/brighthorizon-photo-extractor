# Adversarial Security & Architectural Audit Report: Background Job Extraction Engine

**Project**: `brighthorizon-photo-extractor`  
**Target Areas**: Single-Job Enforcement & Cancellation Safety, Custom Start Date Filtering, Progress Reporting & Metric Privacy, Flat Storage & Backward Compatibility  
**Audit Path**: `.agents/orchestrator_job_engine/security_audit_report.md`  

---

## Executive Summary

An in-depth adversarial security and architectural review was conducted across the background extraction job engine, custom start date selector, single-job per user enforcement, real-time progress reporting, and flat storage implementation.

### Overall Verdict: **FAIL (Critical Concurrency Bugs, Missing Methods, & Privacy Leaks)**

| Area | Status | Critical Vulnerabilities / Architectural Gaps |
|------|--------|----------------------------------------------|
| **1. Single-Job Enforcement & Cancellation Safety** | **FAIL** | Concurrency race conditions in `POST /api/extraction/start`, missing `job.cancel()` method causing server 500 errors, unclosed Playwright browser contexts, and singleton lock file conflicts. |
| **2. Custom Start Date Filtering** | **FAIL** | `parse_date` ignores `timeframe_text` parameter and misparses missing year dates to `now.year`, bypassing start date filters for historical posts; naive string date comparisons omit timezone conversions. |
| **3. Progress Reporting & Metric Privacy** | **FAIL** | Extraction job status is tenant-isolated via JWT, but unauthenticated endpoints (`/api/auth/verify-stream`) leak live Base64 browser screenshots and child profile lists during active credential verification. |
| **4. Flat Storage Enforcement & Compatibility** | **FAIL** | Physical disk storage is flat and backward-compatible, but UI remnants and ZIP archive stream (`archive_stream.py`) expose nested layouts, omit path traversal checks, and lack ZIP filename collision handling. |

---

## Detailed Audit Findings by Inspection Area

---

### 1. Single-Job Per User Enforcement & Cancellation Safety

#### A. Concurrency & Single-Job Race Conditions (`POST /api/extraction/start`)
- **Unsynchronized In-Memory Dictionary**: `_active_jobs: Dict[str, ScraperJob]` in `backend/server.py` is accessed without mutex guards (`threading.Lock` or `asyncio.Lock`).
- **Check-Then-Set Race Condition**: In `start_extraction` (`backend/server.py`):
  ```python
  if tenant_id in _active_jobs and _active_jobs[tenant_id].status["state"] == "running":
      if not req.force:
          return JSONResponse(status_code=409, ...)
  ...
  job = ScraperJob(tenant, pwd, options)
  _active_jobs[tenant_id] = job
  ```
  When two start requests for the same `tenant_id` arrive concurrently, both threads check `_active_jobs` before either thread sets `_active_jobs[tenant_id] = job`. Both evaluation checks pass as `False`, causing two worker threads to spawn concurrently for the exact same user.
- **State Lag Window**: `ScraperJob.__init__` initializes `self.status["state"] = "idle"`. State only transitions to `"running"` when the worker thread begins executing `job.run()`. Any request arriving during this sub-millisecond initialization window reads `state == "idle"` and bypasses single-job enforcement.
- **Multi-Worker Process Isolation**: If FastAPI runs under multi-worker Uvicorn (`--workers > 1`), process memory is isolated per worker process, rendering in-memory dictionaries completely ineffective at enforcing single-job rules across processes.

#### B. Cancellation Safety & Runtime Crashes
- **Missing `cancel()` Method (`AttributeError`)**: `server.py` calls `old_job.cancel()` (in `start_extraction` with `force=True`) and `job.cancel()` (in `cancel_extraction`). However, `ScraperJob` in `backend/scraper_engine.py` **defines no `cancel()` method**. Calling `POST /api/extraction/cancel` or restarting with `force=True` raises an unhandled `AttributeError: 'ScraperJob' object has no attribute 'cancel'`, triggering an HTTP 500 server error.
- **Incomplete Cancellation Flag Checks**: `self._cancelled` is only checked during feed scanning iterations in `extract_child_feed()`. It is completely ignored during long-running operations in `perform_login()` (up to 120s MFA wait, Turnstile solving), `discover_children()`, `scroll_and_load()`, and media HTTP downloads.
- **False Positive Completion State**: If `extract_child_feed()` exits early when `self._cancelled` is set to `True`, control falls through to lines 248–250 of `job.run()`, which sets `self.status["state"] = "completed"` with message `"Extraction finished successfully"`.
- **Browser Context & Zombie Process Leaks**: `job.run()` launches Chromium via `launch_persistent_context` without wrapping context execution in a `try...finally: context.close()` block. On exception or cancellation, Playwright leaves background Chromium processes running as zombies, locking `user_data_dir`.
- **SingletonLock Conflicts**: `job.run()` omits `clean_user_data_locks()` prior to launching Chromium. If a previous job crashed, stale lock files crash context initialization. Conversely, `verify_credentials()` unconditionally calls `clean_user_data_locks()`, which deletes active lock files out from under a running background extraction job.

---

### 2. Custom Start Date Filtering

#### A. Date Parsing & Year Fallback Bug (`backend/scraper_engine.py`)
- **Unused `timeframe_text` Parameter**:
  ```python
  def parse_date(date_text: str, timeframe_text: str) -> str:
      now = datetime.now()
      if not date_text: return now.strftime("%Y-%m-%d")
      m = re.search(r'(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?', date_text)
      if m:
          month, day, year = m.groups()
          if not year: year = now.year  # <--- Bypasses timeframe_text!
  ```
  `parse_date` receives `timeframe_text` (e.g. `"May 2023"`), but `timeframe_text` is completely ignored. When a feed item displays a date without a year (e.g. `"05/12"`), `year` defaults to `datetime.now().year` (2026).
- **Start Date Bypass**: A historical post from May 2023 displaying `"05/12"` is misparsed as `"2026-05-12"`. If `start_date` is `"2025-01-01"`, string comparison `"2026-05-12" < "2025-01-01"` evaluates as `False`, allowing historical photos to bypass the start date filter.

#### B. Timezone & Boundary Comparison
- **Naive ASCII String Comparison**: `start_date` filtering performs naive string comparison (`date_str < self.start_date`) on `YYYY-MM-DD` strings without timezone conversion (EST/EDT vs UTC). (Eastern Time adjustment via `ZoneInfo("America/New_York")` is only performed downstream when setting file mtimes on disk).
- **Omission of Month Tab Pruning**: `extract_child_feed()` does not stop month tab iteration when encountering dates prior to `start_date`; it continues clicking through earlier `timeframe_lis` tabs.

---

### 3. Progress Reporting & Metric Privacy

#### A. Extraction Job Isolation (`/api/extraction/status`)
- **Secure Isolation**: `/api/extraction/status` requires JWT authentication via `Depends(get_current_tenant)`. Active jobs in `_active_jobs` are strictly indexed by the authenticated `tenant_id`. Cross-tenant metric leaks do not occur on extraction job status endpoints.

#### B. Unauthenticated Privacy Leak (`/api/auth/verify-stream` & `/api/auth/verify-progress`)
- **Unauthenticated Email Lookup**: `/api/auth/verify-stream` and `/api/auth/verify-progress` accept an unauthenticated `email` query parameter:
  ```python
  @app.get("/api/auth/verify-stream")
  async def verify_stream(email: str = Query(...), password: str = Query(...)):
      email_clean = email.strip().lower()
      tenant_id = TenantStorage(email_clean).tenant_id
      current_state = _active_verifications.get(tenant_id)
  ```
- **Live Preview & Profile Exposure**: If a target user is currently performing credential verification, an attacker passing the victim's email to `/api/auth/verify-stream` receives `current_state`, exposing live Base64 browser screenshots (`screenshot`), current step details, and discovered child names (`children`).

---

### 4. Flat Storage Enforcement & Backward Compatibility

#### A. Disk Storage & Manifest Schema
- **Flat Storage on Disk**: Physical media items are stored flat under `data/tenants/<tenant_id>/media/<uuid>.dat`.
- **Backward Compatibility**: Decoupling `storage_path` (`media/<uuid>.dat`) from metadata (`original_filename`, `child`, `date`) in `manifest.json` ensures 100% backward compatibility with pre-existing manifest entries and direct media streaming endpoints (`/api/media/{media_id}`).

#### B. UI & ZIP Stream Remnants
- **UI Layout Selection Remnants**: `frontend/src/components/ArchiveManager.tsx` retains UI toggle buttons for selecting "Flat" vs "Nested" layout format and submits `layout_mode` to `/api/archive/create`.
- **ZIP Stream Support**: `backend/archive_stream.py` supports both `flat` (`child/filename`) and `nested` (`child/YYYY/MM/filename`) ZIP archive structures. Flat storage is enforced for on-disk media, but not strictly enforced for ZIP exports.

#### C. ZIP Stream Security Vulnerabilities
- **Path Traversal Risk (Zip Slip)**: Unlike `database.py`, `archive_stream.py` constructs `abs_src = os.path.join(tenant_storage.tenant_dir, rel_path)` without validating `abs_src.startswith(tenant_dir)` and creates `arcname = os.path.join(child, orig_name)` without sanitizing `child` or `orig_name`. If manifest entries contain relative path sequences (`../`), `zf.write()` writes malicious traversal paths into the generated ZIP archive.
- **Filename Collision Risk**: In flat ZIP mode (`child/orig_name`), `archive_stream.py` lacks collision handling or index suffixing if multiple manifest items share the same child name and original filename.

---

## Actionable Recommendations & Architectural Fixes

### 1. Concurrency, Cancellation, & Browser Lifecycle
1. **Implement Mutex Locking & State Guard**: Add a global `threading.Lock()` or `asyncio.Lock()` around `_active_jobs` mutations and reads in `server.py`. Set `job.status["state"] = "running"` immediately upon instantiation in `server.py` before releasing the lock.
2. **Implement `ScraperJob.cancel()`**: Add a `cancel(self)` method to `ScraperJob` in `backend/scraper_engine.py`:
   ```python
   def cancel(self):
       self._cancelled = True
       self.status["state"] = "cancelled"
       self.status["current_step"] = "Cancelled by user"
   ```
3. **Browser Lifecycle & Cleanup**: Wrap Playwright execution inside `job.run()` with `try...finally:` to guarantee `context.close()` and browser termination.
4. **Isolate Lock Cleanup**: Copy user data directories to temporary per-job paths (`user_data_copy_<tenant_id>`) using `rsync` excluding lock files (per `AGENTS.md` rules), avoiding cross-session lock file collisions.

### 2. Custom Start Date Filtering
1. **Fix `parse_date` Year Fallback**: Parse the year from `timeframe_text` when `date_text` omits explicit 4-digit years:
   ```python
   if not year and timeframe_text:
       tf_match = re.search(r'\b(20\d{2})\b', timeframe_text)
       if tf_match: year = int(tf_match.group(1))
   if not year: year = now.year
   ```
2. **Month Tab Pruning**: Early-exit `extract_child_feed` month tab loops when a tab's month/year precedes `start_date`.

### 3. Metric Privacy & Verification Streams
1. **Authenticate Verification Streams**: Require JWT bearer tokens or valid session cookie authentication on `/api/auth/verify-stream` and `/api/auth/verify-progress` instead of allowing raw email lookup query parameters.

### 4. Storage Enforcement & ZIP Stream Hardening
1. **Clean Up UI Remnants**: Remove "Nested" UI buttons from `ArchiveManager.tsx` and default `ArchiveRequest.layout_mode` to `"flat"`.
2. **Harden ZIP Archive Stream**: In `backend/archive_stream.py`, enforce `abs_src.startswith(tenant_storage.tenant_dir)`, sanitize `arcname` with `os.path.basename`, and add unique index counters for duplicate filenames.
