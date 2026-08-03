# Project: Bright Horizons Auth & Extraction Investigation and Fix

## Architecture
- FastAPI Server (`backend/server.py`): Handles REST API endpoints (`/api/auth/...`, `/api/extraction/...`), session management, and SSE log streaming.
- Scraper Engine (`backend/scraper_engine.py` / `main.py`): Manages Playwright Chromium automation, Turnstile challenge handling, Auth0 login stepper, child auto-discovery, cross-domain session cookies, and media download extraction.
- React Frontend (`src/...`): Interactive stepper, login interstitial, and progress reporting.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Deep Logging & Network Tracing | Add fine-grained network tracing (HTTP requests/responses, status codes, set-cookie headers, domain origins, DOM state transitions) across FastAPI server, scraper engine, and Playwright Chromium | none | DONE |
| 2 | Turnstile Fast-Path & Auth0 Credential Entry | Fix `solve_and_wait_turnstile` when `challenge_present=False` to immediately proceed to username/password filling without 50s stalls | M1 | DONE |
| 3 | Cross-Domain Session Persistence & Media Extraction | Ensure initial auth & `discover_children` perform cross-domain OAuth handshake with `mybrightday.brighthorizons.com` and persist all session cookies to `storage_state.json`; ensure background extraction jobs download photos/videos without 401/403 errors | M1, M2 | DONE |
| 4 | E2E Verification & Live System Verification | Run full E2E verification with test credentials (`taccani.massarelli@gmail.com` / `xxTJ8i.5J2KUkkK`) and verify live behavior | M1, M2, M3 | DONE |

## Interface Contracts
### Auth & Scraper Engine
- `solve_and_wait_turnstile(page, timeout)`: Fast-path return when challenge not present; do not block for 50s.
- `ScraperJob.run()` / `perform_login()`: Collect and persist cross-domain cookies (`auth0`, `mybrightday.brighthorizons.com`, `familyinfocenter.brighthorizons.com`) into `storage_state.json`.
- Logging: Output structured tracing logs (request URL, status, headers, domain origins, DOM state changes) to server logs & SSE streams.

## Code Layout
- `backend/server.py`: FastAPI server routes & session state
- `backend/scraper_engine.py`: Playwright scraper engine & login/extraction workflows
- `main.py`: CLI / core extraction logic & helper functions
