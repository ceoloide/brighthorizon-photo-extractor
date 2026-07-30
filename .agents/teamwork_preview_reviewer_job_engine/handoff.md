# Objective & Adversarial Review Handoff Report: Background Job Extraction Engine Security Audit

**Reviewer & Critic Archetype**: Teamwork Reviewer & Adversarial Critic  
**Working Directory**: `/home/antigravity/GitHub/brighthorizon-photo-extractor/.agents/teamwork_preview_reviewer_job_engine`  
**Audit Report Under Review**: `/home/antigravity/GitHub/brighthorizon-photo-extractor/.agents/orchestrator_job_engine/security_audit_report.md`  
**Target Source Files Inspected**:
- `backend/server.py`
- `backend/scraper_engine.py`
- `backend/archive_stream.py`
- `frontend/src/components/ArchiveManager.tsx`

---

## 1. Observation

### Key Code Evidence Verified in Source Files

1. **`backend/server.py`**:
   - **Line 31**: `_active_jobs: Dict[str, ScraperJob] = {}` is declared as a global dict without any `threading.Lock` or `asyncio.Lock`.
   - **Lines 448–476 (`start_extraction`)**:
     ```python
     if tenant_id in _active_jobs and _active_jobs[tenant_id].status["state"] == "running":
         if not req.force:
             return JSONResponse(status_code=409, ...)
         else:
             old_job = _active_jobs.pop(tenant_id, None)
             if old_job:
                 old_job.cancel()
     ...
     job = ScraperJob(tenant, pwd, options)
     _active_jobs[tenant_id] = job
     thread = threading.Thread(target=job.run, daemon=True)
     ```
     No lock wraps the check-and-set logic. `old_job.cancel()` and `job.cancel()` (lines 461, 486) are called directly.
   - **Lines 141–196 (`verify_stream` & `verify_progress`)**: Accept `email` query/body parameters without JWT or session authentication. If `_active_verifications.get(tenant_id)` exists, `current_state` (containing live screenshots and discovered children) is returned/streamed to any caller supplying that email.
   - **Lines 200–268 (`submit-mfa-code`, `interact-preview`, `next-step`)**: All accept unauthenticated `email` parameters to modify or interact with active Playwright browser sessions.

2. **`backend/scraper_engine.py`**:
   - **Class `ScraperJob`**: Defined on line 54. Inspection confirms **NO `def cancel(self)` method exists** anywhere in `ScraperJob`. Calling `job.cancel()` raises `AttributeError: 'ScraperJob' object has no attribute 'cancel'`.
   - **Line 69 (`__init__`)**: Sets `self.status["state"] = "idle"`. State transitions to `"running"` only inside `run()` at line 149, creating an initialization state-lag window.
   - **Lines 155–256 (`run`)**: Playwright context launch (`launch_persistent_context`) is not wrapped in `try...finally: context.close()`. On error or early return, Chromium processes remain open as zombies locking user data directories.
   - **Lines 860–874 (`parse_date`)**:
     ```python
     def parse_date(date_text: str, timeframe_text: str) -> str:
         now = datetime.now()
         if not date_text: return now.strftime("%Y-%m-%d")
         m = re.search(r'(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?', date_text)
         if m:
             month, day, year = m.groups()
             if not year: year = now.year  # <--- timeframe_text parameter is completely unused!
     ```
     `timeframe_text` is accepted as a parameter but never referenced inside the function body.
   - **Lines 735 & 762**: `self._cancelled` is checked only in feed scanning loops. It is omitted in `perform_login`, `discover_children`, and `scroll_and_load`.

3. **`backend/archive_stream.py`**:
   - **Lines 56–73**:
     ```python
     for media_id, item in manifest.items():
         rel_path = item["storage_path"]
         abs_src = os.path.join(tenant_storage.tenant_dir, rel_path)
         if os.path.exists(abs_src):
             ...
             arcname = os.path.join(child, orig_name)
             zf.write(abs_src, arcname=arcname)
     ```
     Omits `abs_src.startswith(tenant_dir)` traversal verification. Omits sanitization on `arcname`. Omits collision handling for duplicate filenames.

4. **`frontend/src/components/ArchiveManager.tsx`**:
   - **Lines 86–113**: Contains UI toggle controls for `"flat"` vs `"nested"` layout and posts `{ layout_mode: layoutMode }` to `/api/archive/create`.

5. **Test Suite Execution**:
   - Executed `PYTHONPATH=. ./.venv/bin/pytest backend/tests/test_security.py`.
   - Result: `11 passed, 1 failed` in 1.44s.
   - Failure detail: `test_mfa_rate_limiting_behavior` expected `[400, 400, 400, 400, 400]` but received `[400, 400, 400, 429, 429]`. `backend/server.py` (line 220) actually DOES enforce rate limiting (`attempts >= 3` returns HTTP 429). The test assertion was written with a flawed expectation.

---

## 2. Logic Chain

1. **Verification of Audit Claims**:
   - *Claim 1.A & 1.B*: In `server.py`, `_active_jobs` is un-gated. Calling `job.cancel()` triggers an unhandled `AttributeError` because `ScraperJob` lacks `cancel()`. Playwright contexts are not cleaned up in `finally` blocks. Stale locks cause initialization failure. All claims are verified directly by code inspection.
   - *Claim 2.A & 2.B*: In `scraper_engine.py`, `parse_date` ignores `timeframe_text`. When feed dates omit a year (e.g. `"05/12"`), `year` becomes `2026`. Historical dates evaluate as future dates, bypassing `start_date` string comparisons (`"2026-05-12" < "2025-01-01"` is `False`). All claims are verified directly by code inspection.
   - *Claim 3.A & 3.B*: `/api/extraction/status` is isolated via JWT. However, `/api/auth/verify-stream` and `/api/auth/verify-progress` take `email` query/body params and expose `_active_verifications[tenant_id]` containing live Base64 screenshots and child lists without authenticating the requester. All claims are verified.
   - *Claim 4.A, 4.B, & 4.C*: Disk storage is flat. UI and `archive_stream.py` retain nested layout options. `archive_stream.py` lacks path containment checks and duplicate filename collision checks. All claims are verified.

2. **Identification of False Positives**:
   - **Zero False Positives**: All 4 target areas in the Audit Report present valid, reproducible architectural defects backed by exact lines of code.

3. **Identification of Missed Security & Concurrency Vectors**:
   - **Missed Vector 1 (Unauthenticated Interactive Control Hijacking)**: The audit report noted privacy leaks on `/api/auth/verify-stream`, but missed that `/api/auth/submit-mfa-code` (line 200), `/api/auth/interact-preview` (line 232), and `/api/auth/next-step` (line 251) also accept unauthenticated `email` parameters, allowing external actors to inject mouse clicks or advance steps in active browser sessions.
   - **Missed Vector 2 (`import-session` Job Reference Overwrite)**: In `server.py` (lines 361-362), `import_session` sets `_active_jobs[tenant_id] = job` without checking if an extraction job is already running for that tenant, destroying the reference to the active extraction job.
   - **Missed Vector 3 (`_active_jobs` Memory Leak)**: `_active_jobs` never purges completed or failed jobs, causing unbounded dictionary memory growth over extended server runtime.
   - **Missed Vector 4 (Redundant DOM Parsing Overhead)**: In `scraper_engine.py` (lines 798-814), `overlay_span` lookup and `parse_date` are executed twice consecutively per feed item.

4. **Assessment of Recommendations**:
   - Recommendations in the audit report are actionable, concrete, and architecturally sound. They correctly prioritize mutex guards, adding `ScraperJob.cancel()`, `try...finally` browser context cleanup, year extraction from `timeframe_text`, stream authentication, and ZIP path containment.

---

## 3. Caveats

- **No Caveats**: All 4 target inspection areas, test suites, and audit claims were fully verified against the source code.

---

## 4. Conclusion & Review Verdict

### Overall Review Verdict: **APPROVE WITH SUPPLEMENTARY FINDINGS**

The Security Audit Report (`security_audit_report.md`) is **accurate, objective, and well-evidenced**. All reported critical findings represent real defects present in the current codebase.

### Review Summary & Findings Table

| Inspection Area | Audit Report Findings | Code Verification | Reviewer Assessment |
|-----------------|-----------------------|-------------------|---------------------|
| **1. Single-Job & Cancellation** | Unlocked `_active_jobs`, missing `cancel()` method (`AttributeError`), zombie browser processes, state lag. | **VERIFIED** (`server.py`:31,448; `scraper_engine.py`:54,155) | **TRUE**. Critical concurrency bugs & runtime crash vectors confirmed. |
| **2. Custom Start Date** | `parse_date` ignores `timeframe_text`, year fallback defaults to `now.year`, bypassing start date filters. | **VERIFIED** (`scraper_engine.py`:860-874) | **TRUE**. Bypasses date filter for historical feed items without year strings. |
| **3. Progress & Privacy** | `/api/extraction/status` is secure; `/api/auth/verify-stream` leaks screenshots & child profiles unauthenticated. | **VERIFIED** (`server.py`:141-196) | **TRUE**. Privacy leak verified. *Add missed control endpoint hijacking findings.* |
| **4. Flat Storage & ZIP Stream** | Physical storage flat; UI & `archive_stream.py` retain nested layout; missing ZIP traversal and collision handling. | **VERIFIED** (`ArchiveManager.tsx`:86; `archive_stream.py`:56-73) | **TRUE**. ZIP stream vulnerabilities confirmed. |

---

## 5. Adversarial Challenge Report

### Missed Security & Concurrency Vectors

1. **Unauthenticated Session Control Hijacking (`interact-preview`, `next-step`, `submit-mfa-code`)**:
   - *Attack Scenario*: An attacker who knows a target user's email can POST to `/api/auth/interact-preview` with arbitrary coordinates while the target is logging in. The server will invoke `job.click_preview(x, y)` on the victim's live XVFB browser page.
   - *Mitigation*: Require session verification tokens or auth headers on interactive preview endpoints.

2. **Session Import Overwrites Active Extraction Job**:
   - *Attack Scenario*: Calling `POST /api/auth/import-session` while an extraction job is running unconditionally overwrites `_active_jobs[tenant_id]`.
   - *Mitigation*: Check if `_active_jobs[tenant_id]` has an active running job before accepting session imports.

3. **`_active_jobs` Dictionary Leak**:
   - *Attack Scenario*: Completed and failed jobs remain in `_active_jobs` forever.
   - *Mitigation*: Implement cleanup routines or prune completed jobs after status retrieval.

4. **Flawed Unit Test Assertion in `test_security.py`**:
   - *Observation*: `test_mfa_rate_limiting_behavior` fails because it asserts 5 consecutive 400 responses, whereas `server.py` line 220 correctly returns 429 after 3 attempts.
   - *Mitigation*: Update unit test expectation to match the implemented rate limiting (`[400, 400, 400, 429, 429]`).

---

## 6. Verification Method

To independently verify these findings:

1. **Verify Missing `cancel()` Method**:
   ```bash
   PYTHONPATH=. ./.venv/bin/python3 -c "from backend.scraper_engine import ScraperJob; print(hasattr(ScraperJob, 'cancel'))"
   # Output: False
   ```

2. **Verify Unused `timeframe_text` in `parse_date`**:
   ```bash
   PYTHONPATH=. ./.venv/bin/python3 -c "from backend.scraper_engine import parse_date; print(parse_date('05/12', 'May 2023'))"
   # Output: 2026-05-12 (Expected 2023-05-12)
   ```

3. **Run Existing Test Suite**:
   ```bash
   PYTHONPATH=. ./.venv/bin/pytest backend/tests/test_security.py
   ```
