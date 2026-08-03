## 2026-07-31T09:35:00Z

<USER_REQUEST>
You are the Implementation Worker for Milestone 1: DOM Parser and Security Isolation modules.

Task:
1. Implement `backend/dom_parser.py` adhering to specifications from Explorer reports in `.agents/explorer_m1_1/analysis.md` and `.agents/explorer_m1_3/analysis.md`:
   - `parse_timeframe_links(page)`
   - `click_timeframe_tile(page, tile_locator)`
   - `extract_feed_items(page)` (scope inside `div.well.left-panel.pull-left`, parse photo `a.fancybox` vs video background-image CSS, HTML unescape `&amp;`)
   - `discover_children_from_family_info(page, context)` (Angular CDK dropdown parsing, `span.actions-menu-item-label` locator, new tab `context.expect_page()` for `dependent_id`)
   - Pure helper utilities (`is_valid_timeframe_text`, `parse_date_overlay`, `extract_obj_id_from_url_or_style`).

2. Implement `backend/security_isolation.py` adhering to specifications in `.agents/explorer_m1_2/analysis.md`:
   - `clean_user_data_locks(user_data_dir)`
   - `prepare_isolated_user_data(source_dir, target_dir)` (using system rsync fast-path with pure-Python shutil fallback, excluding locks)
   - `IsolatedUserDataContext(source_dir)` context manager
   - `mask_sensitive_data(text)`
   - `canonicalize_and_validate_path(base_dir, target_path)` (realpath boundary check)
   - `sanitize_child_name(child_name)`
   - `resolve_child_output_path(base_dir, child_name, relative_filename)`

3. Create unit test suites:
   - `backend/tests/test_dom_parser.py`
   - `backend/tests/test_security_isolation.py`

4. Run build and tests using pytest (.venv/bin/pytest backend/tests/ -v). Verify all existing and new tests pass 100%.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Write your report to `.agents/worker_m1/handoff.md` with complete test results and code paths.
</USER_REQUEST>
