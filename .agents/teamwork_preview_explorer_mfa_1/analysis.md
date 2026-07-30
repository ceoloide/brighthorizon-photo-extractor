# Detailed Investigation Report: Requirement R1 & R2 Audit

## Executive Summary
This report details the audit of Requirements **R1 (Volatile Memory & Zero-Disk Handling)** and **R2 (Session Ownership Verification & Rate Limiting)** across `backend/scraper_engine.py`, `backend/server.py`, `backend/security.py`, and `backend/database.py`.

---

## 1. Requirement R1: Volatile Memory & Zero-Disk Handling

### Requirement Description
Verify that `_mfa_code` is strictly held in memory in `scraper_engine.py` / `server.py`, overwritten/cleared (`_mfa_code = None`) immediately upon ingestion, and completely absent from disk files, database, server logs, stdout, or SSE streams.

### Observations & Code Tracing

1. **`ScraperJob` Initialization & Memory Storage**
   - File: `backend/scraper_engine.py`
   - Lines 60–61:
     ```python
     self._mfa_code: Optional[str] = None
     self._mfa_event = threading.Event()
     ```
   - Analysis: `_mfa_code` is initialized as a private instance attribute on `ScraperJob`.

2. **Ingestion & Validation (`submit_mfa_code`)**
   - File: `backend/scraper_engine.py`
   - Lines 63–70:
     ```python
     def submit_mfa_code(self, code: str) -> bool:
         code_clean = code.strip()
         if not code_clean.isdigit() or len(code_clean) != 6:
             return False
         self._mfa_code = code_clean
         self._mfa_event.set()
         return True
     ```
   - Analysis: The code is accepted into volatile memory (`self._mfa_code`). No file write, database operation, or logging occurs in this method.

3. **Clearing / Overwriting Upon Consumption**
   - File: `backend/scraper_engine.py`
   - Lines 322–323:
     ```python
     code_to_submit = self._mfa_code
     self._mfa_code = None # Overwrite and clear immediately from volatile memory!
     ```
   - Analysis: `_mfa_code` is copied to a local variable `code_to_submit` and immediately set back to `None` prior to submitting to Auth0.
   - **Caveat / Flaw**: If Playwright raises an exception or times out *before* reaching line 322 (or if execution crashes during `wait(timeout=120)`), `_mfa_code` remains set in `ScraperJob` memory until object garbage collection. While still in RAM (not written to disk), clearing it inside a `finally` block or on timeout/failure would harden volatile memory cleanup.

4. **Disk, Database, SSE & Log Audit**
   - **Server Logs / Stdout**:
     - Line 313: `self.log("Auth0 MFA Email Verification required!")` - log message contains NO code payload.
     - Line 325: `self.log("Submitting MFA code to Auth0...")` - log message contains NO code payload.
     - Line 75: Log entry appends timestamped message to `self.status["logs"]` array. No MFA code string is logged.
   - **SSE Streams**:
     - `server.py` line 143 serializes `state` via `json.dumps(state)` in `verify_stream`.
     - `_active_verifications` stores `job`, `status`, `step`, `step_index`, `screenshot`, `children`, `error`, `timestamp`. `_mfa_code` is NOT exposed in the `state` dict returned to the frontend or broadcast over SSE.
   - **Disk & Database Persistence**:
     - `TenantStorage` (`backend/database.py`) only saves `config.enc` and `manifest.enc`. Neither file schema includes `_mfa_code`.
     - No file I/O or SQLite/database operations touch `_mfa_code`.

### Findings for Requirement R1
- ✅ **Memory-Only Storage**: `_mfa_code` resides exclusively on the `ScraperJob` instance in memory.
- ✅ **Immediate Clearing**: Line 323 sets `self._mfa_code = None` immediately upon reading `code_to_submit`.
- ✅ **Zero Disk / Log Leakage**: No evidence of `_mfa_code` being written to disk files, database, log outputs, or SSE payloads.

---

## 2. Requirement R2: Session Ownership Verification & Rate Limiting

### Requirement Description
Verify `POST /api/auth/submit-mfa-code` in `server.py` and `security.py`. Ensure session ownership checks, strict regex sanitization (`^[0-9]{6}$`), rate limiting (max 3 attempts per session window), and automatic 120-second expiration.

### Observations & Code Tracing

1. **Endpoint Signature & Handler**
   - File: `backend/server.py`
   - Lines 180–205:
     ```python
     @app.post("/api/auth/submit-mfa-code")
     def submit_mfa_code(req: MfaRequest):
         email = req.email.strip().lower()
         code = req.code.strip()
         
         if not code.isdigit() or len(code) != 6:
             raise HTTPException(status_code=400, detail="Invalid 6-digit verification code format.")
             
         tenant_storage = TenantStorage(email)
         tenant_id = tenant_storage.tenant_id
         
         verification = _active_verifications.get(tenant_id)
         job = None
         if verification and "job" in verification:
             job = verification["job"]
         elif tenant_id in _active_jobs:
             job = _active_jobs[tenant_id]
             
         if not job:
             raise HTTPException(status_code=404, detail="No active login verification session found for this email.")
             
         success = job.submit_mfa_code(code)
         if not success:
             raise HTTPException(status_code=400, detail="Failed to submit MFA verification code.")
             
         return {"status": "success", "message": "Verification code received. Resuming authentication..."}
     ```

2. **Analysis of Requirement R2 Features**

   - **Input Sanitization**:
     - `server.py` checks `if not code.isdigit() or len(code) != 6:`.
     - `scraper_engine.py` checks `if not code_clean.isdigit() or len(code_clean) != 6:`.
     - ⚠️ **Deficit**: While `.isdigit()` and `len == 6` restricts strings to 6 digits, strict regex matching (`^[0-9]{6}$` or `re.match(r'^[0-9]{6}$', code)`) is specified by R2. Standard `.isdigit()` can accept Unicode digits in Python 3 (e.g. `٠١٢٣٤٥`), though `.isdigit()` on ASCII numbers works as expected. Using `re.match(r'^[0-9]{6}$', code)` is more stringent.

   - **Session Ownership Verification**:
     - 🚨 **CRITICAL VULNERABILITY**: `POST /api/auth/submit-mfa-code` accepts `email` directly in `MfaRequest` body WITHOUT requiring any session token, bearer JWT, or cookie authentication!
     - Any unauthenticated caller who knows a target user's email can submit an MFA code for an active verification session owned by that email.
     - There is no check verifying that the HTTP request submitting the MFA code originates from the same authenticated user or browser session that initiated `verify_stream` or `verify_progress`.

   - **Rate Limiting**:
     - 🚨 **MISSING FEATURE**: There is NO rate limiting mechanism in `server.py` or `security.py` tracking MFA submission attempts (e.g., max 3 attempts per session window).
     - An attacker could attempt brute-forcing MFA codes by sending automated HTTP POST requests to `/api/auth/submit-mfa-code`.

   - **120-Second Timeout / Expiration**:
     - In `scraper_engine.py` (line 318): `got_code = self._mfa_event.wait(timeout=120)`.
     - The background thread waiting for MFA code will time out after 120 seconds if no code is submitted, raising an Exception (`MFA verification timed out after 120 seconds.`).
     - ⚠️ **Deficit**: In `server.py`, `_active_verifications` state cleanup only happens 45 seconds AFTER the verification thread completes (lines 113-117). If a user calls `submit-mfa-code` repeatedly during or after timeout, there is no explicit check verifying whether the session expired or whether attempt counters have been exceeded.

---

## 3. Vulnerabilities & Deficits Matrix

| ID | Category | Description | Affected File / Lines | Risk Level |
|---|---|---|---|---|
| **VULN-R2-01** | Authorization | Missing session ownership check on `POST /api/auth/submit-mfa-code`. Endpoint relies solely on caller-provided `email` without JWT/session token validation. | `backend/server.py`: 180–205 | **HIGH** |
| **VULN-R2-02** | Security Defense | Missing Rate Limiter for MFA code submissions. No tracking or enforcement of max 3 attempts per session window. | `backend/server.py`: 180–205 | **HIGH** |
| **DEFICIT-R2-03** | Input Validation | Regex validation uses `str.isdigit()` instead of strict ASCII regex pattern `^[0-9]{6}$`. | `backend/server.py`: 185, `backend/scraper_engine.py`: 66 | **LOW** |
| **DEFICIT-R1-04** | Volatile Memory | `_mfa_code` is cleared upon read, but not guaranteed to clear if job fails/times out before ingestion completes. | `backend/scraper_engine.py`: 320–324 | **LOW** |

---

## 4. Recommendations for Implementation Team

1. **Add Session Ownership Check**:
   - Issue session token/ID upon `verify_stream` or `verify_progress` start and require `X-Session-ID` header or JWT token on `POST /api/auth/submit-mfa-code`.
2. **Implement Rate Limiter in `security.py` / `server.py`**:
   - Maintain an in-memory dictionary tracking MFA attempt counts per `tenant_id` / session, incrementing on each submission and rejecting with HTTP 429 when attempts > 3.
3. **Enforce Regex Sanitization**:
   - Replace `isdigit()` checks with `re.match(r"^[0-9]{6}$", code)`.
4. **Harden Volatile Memory Cleanup**:
   - Wrap `_mfa_code` consumption in a `try...finally` block in `scraper_engine.py` to ensure `self._mfa_code = None` is executed even if errors occur.
