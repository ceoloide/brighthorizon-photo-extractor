## 2026-08-03T12:58:51Z
You are Worker 3 for the Bright Horizons Auth & Extraction Investigation and Fix task.

Working Directory: /home/antigravity/GitHub/brighthorizon-photo-extractor/.agents/worker_fix_persistent_context

Objective:
Fix the critical Playwright TypeError defect identified by Challenger 2 in `launch_stealth_persistent_context()` in `backend/scraper_engine.py`.

Defect Details:
In `backend/scraper_engine.py` (lines 76-78), `launch_stealth_persistent_context()` sets:
`context_kwargs["storage_state"] = state_file`
and calls `playwright_instance.chromium.launch_persistent_context(**context_kwargs)`.
Playwright's `launch_persistent_context()` method does NOT accept `storage_state` as a keyword argument! When `storage_state.json` exists on disk, `launch_stealth_persistent_context()` crashes with:
`TypeError: BrowserType.launch_persistent_context() got an unexpected keyword argument 'storage_state'`

Fix Instructions:
1. Update `backend/scraper_engine.py` in `launch_stealth_persistent_context()`:
   - Remove `context_kwargs["storage_state"] = state_file` before launching `launch_persistent_context()`.
   - Launch `context = playwright_instance.chromium.launch_persistent_context(**context_kwargs)`.
   - After context is created, check if `os.path.exists(state_file)`. If present, read `storage_state.json`, extract `cookies = state_data.get("cookies", [])`, and if `cookies` is present, call `context.add_cookies(cookies)` inside a `try...except` block.
2. Update `backend/tests/test_scraper_engine.py`:
   - Update `test_launch_stealth_persistent_context_auto_loads_storage_state` to verify `context.add_cookies()` is called when `storage_state.json` exists, rather than asserting `storage_state` kwarg.
3. Run `uv run pytest backend/tests/` to verify all 161 unit tests pass cleanly.

Document your changes in `/home/antigravity/GitHub/brighthorizon-photo-extractor/.agents/worker_fix_persistent_context/handoff.md` and report completion.
