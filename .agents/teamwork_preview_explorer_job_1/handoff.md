# Single-Job Per User Enforcement & Cancellation Safety Analysis

## 1. Observation

### Concurrency & Single-Job Enforcement
- **`backend/server.py` Lines 31**:
  ```python
  _active_jobs: Dict[str, ScraperJob] = {}
  ```
- **`backend/server.py` Lines 444–479 (`POST /api/extraction/start`)**:
  ```python
  @app.post("/api/extraction/start")
  def start_extraction(req: ExtractionRequest, tenant: TenantStorage = Depends(get_current_tenant)):
      tenant_id = tenant.tenant_id
      
      if tenant_id in _active_jobs and _active_jobs[tenant_id].status["state"] == "running":
          if not req.force:
              return JSONResponse(
                  status_code=409,
                  content={
                      "status": "running_conflict",
                      "message": "An extraction job is currently running.",
                      "job": _active_jobs[tenant_id].status
                  }
              )
          else:
              old_job = _active_jobs.pop(tenant_id, None)
              if old_job:
                  old_job.cancel()
                  
      config = tenant.load_config()
      pwd = req.password or config.get("password") or "imported_session"
          
      options = {
          "sync_mode": req.sync_mode,
          "start_date": req.start_date,
          "layout_mode": "flat",
          "child": req.child
      }
      
      job = ScraperJob(tenant, pwd, options)
      _active_jobs[tenant_id] = job
      
      thread = threading.Thread(target=job.run, daemon=True)
      thread.start()
      
      return {"status": "started", "job": job.status}
  ```
- **`backend/scraper_engine.py` Lines 68–74 (`ScraperJob.__init__`)**:
  ```python
  self.status = {
      "state": "idle",
      "current_step": "Initializing",
      "files_downloaded": 0,
      "error": None,
      "logs": []
  }
  ```
- **`backend/scraper_engine.py` Line 149 (`ScraperJob.run`)**:
  ```python
  def run(self):
      self.status["state"] = "running"
  ```

### Cancellation Safety & Browser Cleanup
- **`backend/server.py` Lines 461 & 486**:
  ```python
  old_job.cancel() # line 461 in start_extraction (force=True)
  job.cancel()     # line 486 in cancel_extraction
  ```
- **`backend/scraper_engine.py` Lines 54–147 (`ScraperJob` class methods)**:
  `ScraperJob` defines `self._cancelled = False` on line 66, but **does not define any `cancel()` method anywhere in the class**.
- **`backend/scraper_engine.py` Lines 735–737 & 762–764 (`extract_child_feed`)**:
  ```python
  if self._cancelled:
      self.log("Extraction cancelled by user.")
      return
  ```
- **`backend/scraper_engine.py` Lines 248–250 (`job.run` completion path)**:
  ```python
  self.status["state"] = "completed"
  self.status["current_step"] = "Extraction finished successfully"
  self.log("All extraction tasks completed successfully!")
  ```
- **`backend/scraper_engine.py` Lines 182–191 & 252–255 (`job.run` context lifecycle & error handling)**:
  ```python
  context: BrowserContext = p.chromium.launch_persistent_context(
      user_data_dir,
      **context_kwargs
  )
  ...
  except Exception as e:
      self.status["state"] = "failed"
      self.status["error"] = str(e)
      self.log(f"Extraction failed: {e}")
  ```
  `context.close()` is never called in a `finally` block inside `job.run()`.
- **`backend/scraper_engine.py` Lines 42–52 (`clean_user_data_locks`)**:
  ```python
  def clean_user_data_locks(user_data_dir: str):
      if not os.path.exists(user_data_dir):
          return
      for root, dirs, files in os.walk(user_data_dir):
          for fname in files:
              if "Singleton" in fname or fname == "RunningChromeVersion":
                  try:
                      os.remove(os.path.join(root, fname))
                  except Exception:
                      pass
  ```
  `clean_user_data_locks` is invoked at lines 577 & 581 in `verify_credentials()`, but is **never invoked** in `job.run()` before launching `launch_persistent_context`.

---

## 2. Logic Chain

### A. Concurrency & Single-Job Race Conditions
1. **Unsynchronized Dictionary Access**: `_active_jobs` is mutated and read directly across thread handlers without a mutex (`threading.Lock()` or `asyncio.Lock()`).
2. **Check-Then-Set Vulnerability**: When two concurrent requests to `POST /api/extraction/start` arrive simultaneously for the same `tenant_id`:
   - Both threads check `if tenant_id in _active_jobs and _active_jobs[tenant_id].status["state"] == "running"`.
   - Before either thread completes `_active_jobs[tenant_id] = job`, both evaluate the condition as `False`.
   - Both threads instantiate a `ScraperJob` and call `thread.start()`.
   - Result: Two concurrent worker threads run `job.run()` simultaneously for the exact same tenant.
3. **State Lag Window**: When `job` is instantiated, `job.status["state"]` is set to `"idle"`. It changes to `"running"` only when the spawned thread begins executing `job.run()`. Any request arriving during this sub-millisecond gap will read `state == "idle"` and bypass the single-job check even if `tenant_id in _active_jobs` is true.
4. **Multi-Worker Invalidation**: If FastAPI runs under multi-worker Uvicorn (`--workers > 1`), process memory is isolated. A job active in worker process A is invisible to worker process B, allowing duplicate concurrent jobs per user across processes.

### B. Cancellation Safety & Runtime Crashes
1. **AttributeError on Cancel**: `server.py` invokes `job.cancel()` in both `cancel_extraction` (`/api/extraction/cancel`) and `start_extraction` (`force=True`). Because `ScraperJob` does not implement `def cancel(self):`, executing either endpoint raises `AttributeError: 'ScraperJob' object has no attribute 'cancel'`, resulting in an unhandled HTTP 500 error.
2. **Incomplete Cancellation Flags**: `self._cancelled` is checked only inside `extract_child_feed()` loop iterations. It is ignored during long-running operations in `perform_login()` (up to 120s MFA wait, Turnstile wait, page navigation), `discover_children()`, `scroll_and_load()`, and media file HTTP downloads (`page.request.get()`).
3. **False Positive Completion State**: If `extract_child_feed()` exits early when `self._cancelled` is true, control falls through to lines 248–250 of `job.run()`, which sets `self.status["state"] = "completed"` with message `"Extraction finished successfully"`.
4. **Browser Resource & Zombie Process Leak**: `job.run()` launches Chromium via `launch_persistent_context` without wrapping the context lifecycle in a `try...finally: context.close()` block. If the thread encounters an unhandled exception or exits, Playwright may leave background Chromium processes running as zombies, keeping lock files active in `user_data_dir`.
5. **SingletonLock Race & Crash**:
   - `job.run()` does not clean lock files before calling `launch_persistent_context`. If a prior run crashed, stale `SingletonLock` files cause Chromium launch to crash with `TargetClosedError`.
   - Conversely, `verify_credentials()` unconditionally calls `clean_user_data_locks()` on `user_data_dir`. If called while an extraction job is active, it deletes active Chromium lock files out from under the running browser process.

---

## 3. Caveats
- **Python Thread Cancellation Limitation**: In standard Python, threads cannot be forcibly killed from another thread. Even with a `def cancel(self): self._cancelled = True` method added, any thread currently blocked in synchronous Playwright I/O (e.g. `page.wait_for_selector`) will continue executing until that specific call times out or completes.
- **Single Process Assumptions**: The current `_active_jobs` dictionary structure assumes a single backend process. No distributed or inter-process locking mechanism (e.g. file lock or database row lock) is currently implemented.

---

## 4. Conclusion

1. **Single-Job Enforcement is Vulnerable**: Concurrent start requests suffer from check-then-set race conditions and a state lag window due to lack of thread locking around `_active_jobs`.
2. **Cancellation Endpoint Crashes (`AttributeError`)**: Invoking cancellation or forcing a restart fails with a 500 error because `ScraperJob` lacks a `cancel()` method.
3. **Resource Leak & Zombie Hazards**: Browser contexts are not closed in `finally` blocks, lock cleanup is omitted in `job.run()`, and lock cleanup in `verify_credentials()` interferes with running extraction contexts.

---

## 5. Verification Method

### A. Independent Inspection & Reproduction Commands

1. **Verify Missing `cancel()` Method**:
   Run grep for `def cancel` across the codebase:
   ```bash
   grep -rn "def cancel" backend/
   ```
   *Expected Output*: Only `def cancel_extraction` in `server.py` is returned. No `def cancel` exists in `scraper_engine.py`.

2. **Reproduce Cancellation `AttributeError`**:
   Start the FastAPI server and trigger `POST /api/extraction/cancel`:
   ```bash
   curl -X POST http://127.0.0.1:8000/api/extraction/cancel -H "Authorization: Bearer <TOKEN>"
   ```
   *Expected Result*: HTTP 500 Internal Server Error (`AttributeError: 'ScraperJob' object has no attribute 'cancel'`).

3. **Verify Lack of Locking in `start_extraction`**:
   Inspect `backend/server.py` lines 444–479 for `threading.Lock` or `asyncio.Lock`. Confirm no lock guards `_active_jobs`.

4. **Verify Context Cleanup in `scraper_engine.py`**:
   Inspect `backend/scraper_engine.py` lines 148–256. Confirm `context.close()` is absent from a `finally` block in `job.run()`.
