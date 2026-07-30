# Handoff Report — Custom Start Date Filtering and Progress Reporting / Metric Privacy Analysis

## 1. Observation

### Custom Start Date Filtering & Date Parsing (`backend/scraper_engine.py`)

1. **Unused `timeframe_text` Parameter in `parse_date` (`backend/scraper_engine.py:860-874`)**:
   ```python
   def parse_date(date_text: str, timeframe_text: str) -> str:
       """Parses date string into YYYY-MM-DD format."""
       now = datetime.now()
       if not date_text:
           return now.strftime("%Y-%m-%d")
       m = re.search(r'(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?', date_text)
       if m:
           month, day, year = m.groups()
           if not year:
               year = now.year
           else:
               year = int(year)
               if year < 100: year += 2000
           return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
       return now.strftime("%Y-%m-%d")
   ```
   - `parse_date` accepts `timeframe_text` (e.g. `"May 2023"`), but `timeframe_text` is completely ignored inside the function.
   - When a feed post overlay displays a month/day string without a year (e.g. `"05/12"`), `year` defaults to `now.year` (`datetime.now().year`).

2. **Filtering Logic & Timezone Handling (`backend/scraper_engine.py:803-806`)**:
   ```python
   # Check Custom Start Date condition
   if self.start_date and date_str < self.start_date:
       self.log(f"Post date {date_str} is before custom start date {self.start_date}. Skipping.")
       continue
   ```
   - `start_date` filtering performs a naive string comparison (`date_str < self.start_date`) on `"YYYY-MM-DD"` strings.
   - There is no timezone conversion (UTC vs `America/New_York` / Eastern Time) applied during date filtering. Timezone handling is only performed downstream in `set_eastern_timestamp` (`backend/scraper_engine.py:891-899`) after saving files to disk.
   - Filtering does not prune month iterations; `extract_child_feed` continues navigating prior `timeframe_lis` tabs even when post dates fall below `start_date`.

3. **Duplicate Date Overlay Parsing Block (`backend/scraper_engine.py:797-815`)**:
   - `overlay_span = item.locator("span.name span").first` and `parse_date(...)` are called twice in contiguous lines for the same feed item.

---

### Progress Reporting & Metric Privacy (`backend/server.py` & `backend/scraper_engine.py`)

1. **Tenant Isolation of Active Extraction Jobs (`backend/server.py:490-501`)**:
   ```python
   @app.get("/api/extraction/status")
   def extraction_status(tenant: TenantStorage = Depends(get_current_tenant)):
       tenant_id = tenant.tenant_id
       if tenant_id in _active_jobs:
           return _active_jobs[tenant_id].status
       return { ... }
   ```
   - `/api/extraction/status` enforces JWT authentication via `Depends(get_current_tenant)`.
   - Active jobs in `_active_jobs` are strictly indexed by `tenant_id` derived from the validated JWT token payload.

2. **Unauthenticated Information Leak in Verification Streams (`backend/server.py:141-195`)**:
   ```python
   @app.get("/api/auth/verify-stream")
   async def verify_stream(email: str = Query(...), password: str = Query(...)):
       email_clean = email.strip().lower()
       ...
       tenant_storage = TenantStorage(email_clean)
       tenant_id = tenant_storage.tenant_id
       
       current_state = _active_verifications.get(tenant_id)
       if not current_state or current_state.get("status") in ["failed", "completed_reset"]:
           current_state = _start_verification_thread(email_clean, password, tenant_storage)

       async def event_generator():
           while True:
               state = _active_verifications.get(tenant_id)
               ...
               clean_state = {k: v for k, v in state.items() if k != "job"}
               payload = json.dumps(clean_state)
               yield f"data: {payload}\n\n"
   ```
   - When an active verification session exists in `_active_verifications` for a given `tenant_id`, any caller passing that user's `email` to `/api/auth/verify-stream` (or `/api/auth/verify-progress`) receives the `current_state` object.
   - `current_state` includes live browser Base64 screenshots (`screenshot`), current authentication steps (`step`, `step_index`), and discovered child profiles (`children`).

---

## 2. Logic Chain

1. **Date Parsing Fallback Anomaly**:
   - Observation: `parse_date` receives `timeframe_text` (which contains month and year, e.g. `"jun 2024"`), but does not use it. If `date_text` is `"06/15"`, `parse_date` sets `year = now.year` (e.g. 2026).
   - Reasoning: An older post from June 2024 will be misparsed as `"2026-06-15"`.
   - Impact on Filtering: If `start_date` is set to `"2025-01-01"`, the misparsed date `"2026-06-15"` will satisfy `date_str >= self.start_date` and fail to filter out historical photos from 2024.

2. **Timezone Boundary Handling**:
   - Observation: Dates are parsed into naive `"YYYY-MM-DD"` strings and compared directly with ASCII string operators.
   - Reasoning: Bright Horizons portal timestamps and host execution environments operate in local time or UTC. While string comparison works for canonical `YYYY-MM-DD` representations, lack of explicit timezone offset awareness (e.g., Eastern Time vs UTC) creates boundary edge cases near midnight (e.g. UTC vs EST/EDT offset shifts).

3. **Metric Privacy & Verification Stream Leakage**:
   - Observation: `/api/extraction/status` is guarded by JWT authentication and uses `_active_jobs[tenant_id]`. `/api/auth/verify-stream` and `/api/auth/verify-progress` query params accept unauthenticated `email`.
   - Reasoning: Extraction metrics during active extraction jobs are properly isolated. However, during login verification, if an attacker queries `/api/auth/verify-stream?email=target@example.com&password=dummy` while the victim user is verifying credentials, `_active_verifications.get(tenant_id)` returns the victim's active verification state, exposing live browser preview screenshots and child profile names.

---

## 3. Caveats

1. **Target Portal DOM Dependencies**:
   - Bright Horizons DOM overlay formatting (`span.name span`) determines `date_text`. If the portal includes explicit 4-digit years in `date_text` for all posts, the year fallback issue in `parse_date` only triggers when year is omitted.
2. **Execution Context**:
   - Analysis performed strictly via code inspection and test execution (`PYTHONPATH=. .venv/bin/pytest backend/tests/test_security.py`).

---

## 4. Conclusion

1. **Custom Start Date Filtering Assessment**:
   - **Vulnerability / Bug**: `parse_date` ignores `timeframe_text`, causing posts lacking explicit year components in `date_text` to default to `now.year`. This can bypass `start_date` filtering for historical posts.
   - **Improvement**: `parse_date` should extract the year from `timeframe_text` when `date_text` lacks a year. Date filtering should also implement month-level pruning during timeframe iteration to improve efficiency.

2. **Progress Reporting & Metric Privacy Assessment**:
   - **Extraction Jobs**: `/api/extraction/status` live progress metrics (`current_child`, `current_month`, `current_date`, `files_downloaded`) are properly isolated per tenant via JWT authentication (`get_current_tenant`).
   - **Verification Sessions**: `/api/auth/verify-stream` and `/api/auth/verify-progress` permit unauthenticated access to active verification session states (including live session screenshots and child names) by email lookup when a verification session is already in progress.

---

## 5. Verification Method

To independently verify these findings:

1. **Test Security Suite**:
   ```bash
   PYTHONPATH=. .venv/bin/pytest backend/tests/test_security.py
   ```
2. **Inspect Code Files**:
   - Inspect date parsing logic in `backend/scraper_engine.py:860-874`.
   - Inspect custom start date comparison in `backend/scraper_engine.py:803-806`.
   - Inspect verification stream access in `backend/server.py:141-195`.
