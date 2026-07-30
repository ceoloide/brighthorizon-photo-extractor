# Project: brighthorizon-photo-extractor audit

## Architecture
- Backend: Python FastAPI (`server.py`), Scraper Engine (`scraper_engine.py`) using Playwright for browser automation, storage state handling, job management, cancellation flags, and session cookie reuse.
- Frontend: React / TypeScript web UI (`frontend/src/`) with `Dashboard.tsx` (`<header>`, `showLogs` console log drawer), `App.tsx`, `ExtractionPanel.tsx`, etc.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Job Cancellation Responsiveness | `server.py`, `scraper_engine.py` cancellation logic, Playwright page/context/browser teardown, `ScraperJob` status update | none | IN_PROGRESS |
| 2 | Session Cookie & LocalStorage Reuse | `scraper_engine.py` (`ScraperJob.run`), `storage_state.json` loading via `browser.new_context(storage_state=...)`, login bypass logic | none | IN_PROGRESS |
| 3 | UI Header Branding & Log Drawer | `frontend/src/components/Dashboard.tsx` (header title "Bright Horizon Photo Extractor", Sync chip removal, `showLogs=false` default state) | none | DONE |

## Interface Contracts
- `POST /api/extraction/cancel`: Cancels running extraction for tenant, calls `job.cancel()`, closes Playwright page/context/browser, returns success, sets status to `'cancelled'`.
- `ScraperJob.run()`: Checks for `storage_state.json`, initializes `browser.new_context(storage_state=...)`, validates session cookies/localStorage, skips login steps if valid.
- UI Header & Drawer: Header title renders "Bright Horizon Photo Extractor", no Sync chip rendered, Log drawer `showLogs` defaults to `false`.
