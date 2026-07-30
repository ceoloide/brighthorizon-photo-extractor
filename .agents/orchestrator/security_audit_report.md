# Comprehensive Security Audit Report: Desktop-Only Session Import & Device Cookie Authentication Flow

**Target Repository:** `brighthorizon-photo-extractor`  
**Working Directory:** `/home/antigravity/GitHub/brighthorizon-photo-extractor`  
**Audit Date:** July 30, 2026  
**Auditor:** Teamwork Security Orchestrator & Forensic Audit Suite  

---

## Executive Summary

An in-depth adversarial architecture and security audit was performed on the proposed Desktop-Only Session Import & Device Cookie Authentication Flow for `brighthorizon-photo-extractor`. The audit evaluated 4 core security components:
1. **Mobile Device Guardrail**
2. **Address Bar JavaScript Snippet & Client-Side Validation**
3. **Multi-Tenant Device Cookie (`bh_tenant_token`)**
4. **Playwright Session Restoration (`ScraperJob`)**

### Overall Audit Verdict: **FAIL** (Requires Critical Security & Runtime Fixes)

While the project demonstrates solid underlying cryptographic primitives (AES-256-GCM, PBKDF2HMAC, path traversal sanitization), several critical runtime crash bugs, authentication bypasses, incomplete payload validations, and session handling flaws were identified in the session import and authentication layers.

---

## Audit Evaluation Matrix

| Component | Status | Key Findings / Critical Issues |
| :--- | :---: | :--- |
| **1. Mobile Device Guardrail** | **FAIL** | Client-side React check only (`App.tsx`). Readily bypassed via direct API calls (`curl`/Postman) or browser DevTools UA/viewport emulation. |
| **2. Address Bar JS Snippet & Validation** | **FAIL** | Missing key presence validation (`auth0`, `dtCookie`, `OptanonConsent`, `_ga`, `_pendo_meta`, `_fs_uid`). Unauthenticated session injection permits account takeover. |
| **3. Multi-Tenant Cookie (`bh_tenant_token`)** | **FAIL** | Server crash (`TypeError` missing `tenant_id` arg in `create_jwt_token`), `secure=False` cookie flag, duplicate FastAPI route overwrite breaking cookie auth. |
| **4. Playwright Session Restoration** | **FAIL** | Playwright context launched without `storage_state=state_file` parameter. Expired cookie redirects not handled explicitly in `discover_children`. |

---

## In-Depth Analysis by Audit Area

### Area 1: Mobile Device Guardrail
* **Evaluation Status:** **FAIL** (Non-bypass proof / Client-side only)
* **Code Locations:** `frontend/src/App.tsx` (Lines 13–17, 67–69), `frontend/src/components/MobileBlocked.tsx`

#### Detailed Assessment
* **Implementation Logic:**
  ```typescript
  const checkMobile = () => {
    const mobileUA = /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(navigator.userAgent);
    const smallScreen = window.innerWidth < 768;
    setIsMobile(mobileUA || smallScreen);
  };
  ```
* **Bypass Vectors & Vulnerabilities:**
  1. **Client-Side Only Enforcement:** The mobile check is executed solely within the browser DOM context before rendering `<MobileBlocked />`. The backend FastAPI server (`backend/server.py`) has no User-Agent checking or viewport validation middleware.
  2. **Direct API Exploitation:** An attacker on a mobile device can bypass the UI restriction entirely by calling `POST /api/auth/import-session` via `curl`, Postman, or mobile browser scripts.
  3. **DevTools Emulation:** A user can easily toggle Desktop View / User-Agent spoofing in Chrome/Safari mobile tools.
  4. **State Flashing on Window Resize:** Resizing the window dynamically toggles `isMobile`, unmounting `<DesktopSessionStepper />` and abruptly losing local component state.

---

### Area 2: Address Bar JS Snippet & Client-Side Validation
* **Evaluation Status:** **FAIL** (Incomplete validation & unauthenticated session injection)
* **Code Locations:** `frontend/src/components/DesktopSessionStepper.tsx` (Lines 18, 36–56), `backend/server.py` (Lines 306–368)

#### Detailed Assessment
* **Snippet Format:**
  ```javascript
  (function(){var d={cookies:document.cookie,storage:JSON.stringify(localStorage)};if(window.copy){copy(JSON.stringify(d));alert("Session copied to clipboard!");}else{prompt("Copy Session Payload:",JSON.stringify(d));}})();
  ```
* **Bypass Vectors & Vulnerabilities:**
  1. **Missing Required Cookie & Storage Key Validation:**
     * **Requirement:** Client-side React components must validate cookie keys (`auth0`, `dtCookie`, `OptanonConsent`, `_ga`) and LocalStorage keys (`_pendo_meta`, `_fs_uid`).
     * **Actual Implementation:** `validateLocalPayload` in `DesktopSessionStepper.tsx` only verifies `!data.cookies && !data.storage`. It does NOT parse or check for the required keys.
     * **Impact:** Empty or dummy payloads pass client validation, causing downstream server/scraper errors.
  2. **Unauthenticated Session Injection & Account Takeover (CRITICAL):**
     * `POST /api/auth/import-session` accepts any `email` and payload without requiring prior authentication or verification of account ownership.
     * An attacker can import arbitrary session cookies under a victim's email address and obtain a valid `bh_tenant_token` JWT signed for that victim.
  3. **Silent Error Handling on LocalStorage Parsing:**
     * In `backend/server.py` line 340, `except Exception as e:` prints the exception to stdout but allows execution to continue, issuing valid JWT device tokens even when storage string parsing fails.

---

### Area 3: Multi-Tenant Device Cookie (`bh_tenant_token`)
* **Evaluation Status:** **FAIL** (Runtime Server Crash & Insecure Cookie Flags)
* **Code Locations:** `backend/server.py` (Lines 357–365, 369–382, 420–428), `backend/security.py` (Lines 88–132)

#### Detailed Assessment
* **Bypass Vectors & Vulnerabilities:**
  1. **Immediate Server Crash Vector (`TypeError`):**
     * In `backend/security.py`, `create_jwt_token(email: str, tenant_id: str, expires_in: int = 86400 * 7)` requires two positional arguments (`email` and `tenant_id`).
     * In `backend/server.py` line 357:
       ```python
       jwt_token = create_jwt_token(email)
       ```
     * **Impact:** Invoking `POST /api/auth/import-session` causes an immediate unhandled `TypeError: create_jwt_token() missing 1 required positional argument: 'tenant_id'`, crashing the server request handler with HTTP 500!
  2. **Insecure Cookie Transmission (`secure=False`):**
     * In `backend/server.py` line 364, `response.set_cookie` sets `secure=False`.
     * **Impact:** The device cookie `bh_tenant_token` can be transmitted over unencrypted HTTP, exposing sessions to Wi-Fi sniffing and MITM attacks.
  3. **Duplicate FastAPI Endpoint Overwrite (`/api/auth/me`):**
     * `backend/server.py` defines `@app.get("/api/auth/me")` twice (Lines 369 & 420).
     * The first handler parses cookie `bh_tenant_token`. The second handler uses `get_current_tenant` dependency (expecting `Authorization: Bearer`).
     * **Impact:** FastAPI silently overwrites the first route handler. Any client relying on HTTP cookie authentication receives an HTTP 401 Unauthorized error unless an explicit `Authorization: Bearer` header is supplied.

---

### Area 4: Playwright Session Restoration
* **Evaluation Status:** **FAIL** (Unloaded session state & unhandled auth redirects)
* **Code Locations:** `backend/scraper_engine.py` (Lines 151–204, 298–303, 552–612)

#### Detailed Assessment
* **Bypass Vectors & Vulnerabilities:**
  1. **Missing `storage_state` Parameter in Playwright Context Launch:**
     * `import_session` saves session data to `data/tenants/<tenant_id>/user_data/storage_state.json`.
     * In `ScraperJob.run` (line 180) and `verify_credentials` (line 496), `launch_persistent_context` is invoked with `user_data_dir` but **without `storage_state=state_file`**.
     * Playwright's `launch_persistent_context` does NOT automatically load loose `storage_state.json` files inside the user data directory.
     * **Impact:** Playwright launches an unauthenticated browser context, failing cookie-based session restoration and forcing a fallback to credentials login (`perform_login`).
  2. **Expired Cookie Redirect Handling in `discover_children`:**
     * When navigating to `https://familyinfocenter.brighthorizons.com/home`, if session cookies are expired, the browser is redirected to the SSO login page (`https://familyinfocenter.brighthorizons.com/okta/login`).
     * `discover_children` fails to check whether the current URL is a login redirect, resulting in generic locator timeouts on `span:has-text('Actions')` instead of raising a clear session expired exception.

---

## Actionable Remediation Roadmap

1. **Fix Server Crash Bug (`backend/server.py`):**
   Update line 357 in `backend/server.py`:
   ```python
   jwt_token = create_jwt_token(email, tenant_storage.tenant_id)
   ```

2. **Consolidate Endpoint `/api/auth/me` (`backend/server.py`):**
   Remove the duplicate `@app.get("/api/auth/me")` handler and update the single handler to accept tokens from both the `bh_tenant_token` cookie and the `Authorization: Bearer` header.

3. **Harden Cookie Security Attributes:**
   Set `secure=True` (or `secure=request.url.scheme == "https"`) and `samesite="lax"` when setting `bh_tenant_token`.

4. **Enhance Client-Side & Server-Side Session Key Validation:**
   In `frontend/src/components/DesktopSessionStepper.tsx` and `backend/server.py`, validate that cookies contain `auth0`, `dtCookie`, `OptanonConsent`, `_ga` and LocalStorage contains `_pendo_meta`, `_fs_uid` before accepting imports.

5. **Fix Playwright Session Restoration (`backend/scraper_engine.py`):**
   In `ScraperJob.run` and `verify_credentials`, pass `storage_state=os.path.join(user_data_dir, "storage_state.json")` into `launch_persistent_context`.

6. **Add Backend User-Agent / Guardrail Middleware:**
   Add lightweight server-side User-Agent inspection if desktop-only constraints are mandatory at the API layer.

---

*Security Audit completed and reported by Teamwork Orchestrator.*
