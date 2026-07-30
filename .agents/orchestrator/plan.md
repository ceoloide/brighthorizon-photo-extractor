# Audit Execution Plan — brighthorizon-photo-extractor

## Objective
Perform an in-depth adversarial audit of `brighthorizon-photo-extractor` focusing on three critical audit items:
1. **Job Cancellation Responsiveness**: Verify `POST /api/extraction/cancel` immediately closes active Playwright pages/contexts/browsers and updates `ScraperJob` status to `'cancelled'`.
2. **Session Cookie & LocalStorage Reuse**: Audit `ScraperJob.run()` to ensure it loads `storage_state.json` via `browser.new_context(storage_state=...)` and skips full login steps when session cookies are valid.
3. **UI Header Branding & Log Drawer**: Confirm header title is "Bright Horizon Photo Extractor", Sync chip is removed, and console logs are collapsed by default.

## Milestones & Verification Steps

### Milestone 1: Job Cancellation Responsiveness
- Inspect backend/server.py and scraper engine job cancellation methods (`job.cancel()`, `cancel_extraction`, process/page cleanup).
- Check race conditions: what happens if cancellation occurs during page navigation, download, or month loop?
- Verify Playwright context/browser/page cleanup and job status transition to `'cancelled'`.

### Milestone 2: Session Cookie & LocalStorage Reuse
- Inspect `ScraperJob.run()`, `storage_state.json` loading, cookie validity checks, and session restoration in Playwright context (`browser.new_context(storage_state=...)`).
- Verify whether full login steps (email/password/MFA/Turnstile) are skipped when valid session cookies/storage are present.
- Identify potential edge cases where expired session cookies cause crashes vs graceful fallback.

### Milestone 3: UI Header Branding & Log Drawer
- Inspect frontend React components (`App.tsx`, `Header.tsx`, `LogDrawer.tsx`, etc.).
- Verify page header title text is exactly "Bright Horizon Photo Extractor".
- Verify Sync chip has been removed from the UI.
- Verify console log drawer default state is collapsed (`isOpen = false` or equivalent).

## Execution Strategy
- Spawn specialist Explorer / Challenger / Auditor subagents to audit backend code, frontend code, and run tests/verification scripts.
- Synthesize all findings and verify each milestone against acceptance criteria.
- Produce final audit verdict and report to Sentinel.
