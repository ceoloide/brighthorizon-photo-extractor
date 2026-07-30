# Investigation Report: Requirement R3 (Headful Xvfb & Turnstile Bypass) Audit

**Target File**: `backend/scraper_engine.py`  
**Auditor**: Explorer 2  
**Date**: 2026-07-29  

---

## Executive Summary
This report audits the implementation of **Requirement R3** (Headful Xvfb Display, Turnstile Bypass, Singleton Lock Avoidance, and Resource/Exception Handling) in `backend/scraper_engine.py`.

Overall Assessment:
1. **Headful Xvfb Display Setup**: **PASSED**. `ensure_xvfb_display()` and `headless=False` in `launch_persistent_context` are correctly configured.
2. **Turnstile Iframe Checkbox Handling**: **PASSED**. Turnstile iframe detection and coordinate click `(x=30, y=30)` on `body` in `perform_login` are correctly implemented.
3. **Persistent Browser Singleton Lock Avoidance**: **NEEDS REMEDIATION**. The codebase uses `tenant_storage.user_data_dir` directly for both long-running extraction jobs and credentials verification without rsync/copying lock-free browser context (`user_data_copy`) as specified in `AGENTS.md`.
4. **Resource Handling & Teardown**: **NEEDS REMEDIATION**. Playwright `BrowserContext` is opened inside `with sync_playwright() as p:` but lacks a `try...finally: context.close()` block, which can cause process/lock file leaks on exceptions.

---

## Detailed Code Audit by Requirement Item

### 1. Headful Xvfb Display & Turnstile Bypass Setup
- **Code Locations**: `backend/scraper_engine.py` lines 20–30 (`ensure_xvfb_display`), lines 113–135 (`run`), and lines 395–416 (`verify_credentials`).
- **Observations**:
  - `ensure_xvfb_display()` checks `os.environ.get("DISPLAY")`. If missing, it attempts to start `pyvirtualdisplay.Display(visible=0, size=(1280, 720))` or falls back to `Xvfb :99 -screen 0 1280x720x24 > /dev/null 2>&1 &` and sets `os.environ["DISPLAY"] = ":99"`.
  - In both `run()` and `verify_credentials()`, `context_kwargs` explicitly sets `"headless": False` and includes `--disable-blink-features=AutomationControlled` alongside `--no-sandbox` and `--disable-dev-shm-usage`.
  - Pre-queries FlareSolverr (`FLARESOLVERR_URL` default `http://192.168.1.176:8191/v1`) to obtain initial Cloudflare clearance cookies and User-Agent before launching Chromium.
- **Verification**:
  - `ensure_xvfb_display()` is invoked prior to launching `sync_playwright()` in both execution paths.

### 2. Turnstile Iframe Checkbox Handling
- **Code Location**: `backend/scraper_engine.py` lines 270–281 (`perform_login`).
- **Observations**:
  - In `perform_login()`, after filling the Auth0 username, the engine loops through `page.frames` looking for any frame with `"challenges.cloudflare.com"` in `f.url`.
  - When `cf_frame` is located, it executes `cf_frame.click("body", position={"x": 30, "y": 30}, force=True)` followed by a 3000ms delay.
  - The click operation is safely enclosed in a `try...except Exception as e:` block to prevent minor click errors from crashing the login pipeline.
- **Verification**:
  - Verified frame detection URL string `"challenges.cloudflare.com"` and click target coordinates `{"x": 30, "y": 30}` match Cloudflare Turnstile DOM behavior documented in test scripts and `AGENTS.md`.

### 3. Persistent Browser Singleton Lock Avoidance
- **Code Locations**: `backend/scraper_engine.py` lines 107/132 & 392/413; `backend/database.py` line 17; `AGENTS.md` section 1.
- **Observations**:
  - `AGENTS.md` guidelines state:
    > If you attempt to launch a headful or headless Playwright context using `./user_data` while another instance is already running (e.g. during a background scrape), Chromium will fail with a `TargetClosedError` due to database/singleton locks.
    > Workaround: For diagnostic or debugging runs in parallel, always copy the user data directory to a copy path, omitting lock files (`Singleton*`, `RunningChromeVersion`, `*Lock*`).
  - In `scraper_engine.py`, `user_data_dir = self.tenant_storage.user_data_dir` is passed directly to `p.chromium.launch_persistent_context(user_data_dir, ...)`.
  - While `server.py` guards against concurrent `ScraperJob.run()` executions for the same tenant ID via `_active_jobs`, concurrent call to `verify_credentials()` during an extraction job (or starting a verification call when a previous browser instance didn't close cleanly) will trigger Chromium singleton lock failure (`TargetClosedError`).
- **Recommendation**:
  - Implement a lock-free session directory helper (e.g. copying `user_data` to a temporary directory omitting `Singleton*`, `RunningChromeVersion`, `*Lock*` before launch, or handling lock cleanup) for verification and parallel diagnostic sessions.

### 4. Resource Handling, Exception Catching, Deadlock/Hang Prevention & Context Teardown
- **Code Locations**: `backend/scraper_engine.py` lines 114–189, 318, 396–471.
- **Observations**:
  - **Hang/Deadlock Prevention**:
    - `_mfa_event.wait(timeout=120)` in line 318 prevents thread deadlocks when waiting for user-submitted MFA codes.
    - `detect_page_state(page, max_wait_sec=35)` line 190 uses a bounded loop with `time.time()` checks.
    - FlareSolverr request line 89 uses explicit HTTP timeout (`timeout=70`).
    - Playwright page element waits use explicit timeouts (`timeout=25000`, `timeout=15000`).
  - **Exception Catching**:
    - High-level `try...except` in `run()` and `verify_credentials()` logs errors and updates job status to `"failed"`.
    - Granular `try...except` in `discover_children()` and `extract_child_feed()` prevents single card/item parsing failures from aborting the entire scrape.
  - **Context Teardown & Leaks**:
    - In `run()` and `verify_credentials()`, `context` is launched with `p.chromium.launch_persistent_context(...)` inside `with sync_playwright() as p:`.
    - There is **no `try...finally: context.close()`** wrapping the browser lifecycle. If an exception occurs, `context` is not explicitly closed, leaving browser processes and lock files active until process termination.

---

## Proposed Patch / Code Modifications

To resolve Singleton Lock risk and BrowserContext leakage, the following modifications are proposed for `backend/scraper_engine.py`:

```python
# Proposed helper function for safe user data dir handling:
import shutil
import tempfile

def create_clean_user_data_dir(source_dir: str) -> str:
    """Creates a temporary copy of user_data directory omitting Chromium singleton lock files."""
    temp_dir = tempfile.mkdtemp(prefix="user_data_copy_")
    if os.path.exists(source_dir):
        for item in os.listdir(source_dir):
            if any(item.startswith(p) for p in ["Singleton", "RunningChromeVersion"]) or "Lock" in item:
                continue
            s = os.path.join(source_dir, item)
            d = os.path.join(temp_dir, item)
            if os.path.isdir(s):
                shutil.copytree(s, d, symlinks=True, ignore=shutil.ignore_patterns("Singleton*", "RunningChromeVersion", "*Lock*"))
            else:
                shutil.copy2(s, d)
    return temp_dir

# In ScraperJob.run() and verify_credentials():
# Wrap context creation in try...finally to guarantee context.close():
context = None
try:
    context = p.chromium.launch_persistent_context(user_data_dir, **context_kwargs)
    ...
finally:
    if context:
        try:
            context.close()
        except Exception:
            pass
```

---

## Verification Commands
To verify the existing test suite and security module integrity:
```bash
PYTHONPATH=. ./.venv/bin/pytest backend/tests
```
Result: `8 passed in 0.84s`.
