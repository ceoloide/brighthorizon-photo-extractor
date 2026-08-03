# Milestone 1 Code Review & Stress-Test Handoff Report

## 1. Observation

### Test Suite Execution
- **Command executed**: `.venv/bin/pytest backend/tests/ -v`
- **Result**: `1 failed, 83 passed in 1.90s`
- **Verbatim Failure Output**:
  ```
  FAILED backend/tests/test_dom_parser_adversarial.py::TestExtractObjIdAdversarial::test_multiple_urls_in_css_background
  AssertionError: assert 'vid777' is None
  ```

### Direct Code Inspection Findings

1. **`backend/dom_parser.py:20` & `backend/dom_parser.py:118` (`TIMEFRAME_REGEX` and `parse_timeframe_links`)**:
   - `TIMEFRAME_REGEX = re.compile(r'^[a-z]{3}\s+\d{4}$', re.IGNORECASE)`
   - Matches any 3-letter word followed by 4 digits (e.g., `"foo 2026"`, `"all 2026"`, `"cat 2025"`).
   - In `parse_timeframe_links` (line 118):
     `month_num = months_map.get(month_name, 1)`
     Non-month 3-letter words matching the regex default to month 1 (January).

2. **`backend/dom_parser.py:32-64` (`parse_date_overlay`)**:
   - Matches `^(\d{1,2})/(\d{1,2})$` and `^(\d{1,2})/(\d{1,2})/(\d{2,4})$`.
   - Textual date formats ("Jun 15, 2026", "June 15", "15 Jun 2026"), relative dates ("Today", "Yesterday"), dot/dash formats ("06.15.2026"), and ISO dates ("2026-06-15") do not match `m1` or `m2`.
   - They silently fall back to line 63:
     `return f"{default_year:04d}-{now.month:02d}-{now.day:02d}"`
     which assigns current month/day to historical post dates.
   - Out-of-bound numerical strings like `"99/99"` produce invalid ISO date strings (`"2026-99-99"`).

3. **`backend/dom_parser.py:82` (`extract_obj_id_from_url_or_style`)**:
   - `match_style = re.search(r'url\([\'"]?([^\'"]+)[\'"]?\)', style_clean)`
   - Performs a case-sensitive search without `re.IGNORECASE`. CSS styles using `URL(...)` or `Url(...)` fail to match.
   - Searches for the first `url(...)` without checking if it contains `obj_attachment` or `obj=`. If multiple background URLs exist (e.g. background icon before media URL), it extracts the wrong URL.
   - Photo posts with hrefs lacking `obj_attachment` (e.g. `/remote/v1/media?obj=p555`) trigger `"obj_attachment" not in href_clean` and are misclassified as `is_video = True`.

4. **`backend/security_isolation.py` Assessment**:
   - `prepare_isolated_user_data`: Uses `rsync -a --delete --exclude=Singleton* ...` with `shutil.copytree` fallback and `clean_user_data_locks`. Successfully prevents Playwright persistent profile lock contention.
   - `mask_sensitive_data` & `SanitizedLogger`: Sanitizes passwords, MFA codes (6-digit), JWT/Bearer tokens, session cookies (`AWSALB`, `JSESSIONID`), and custom secrets.
   - `canonicalize_and_validate_path`: Enforces strict base directory containment, checks null bytes (`\x00`), handles realpath resolution, and prevents prefix overlap attacks.
   - `sanitize_child_name` & `resolve_child_output_path`: Sanitizes child directory names and builds safe media directory paths.

5. **Integrity Violations Check**:
   - Searched source code for hardcoded test outputs, facade/mock implementations, external tool shortcuts, or fabricated logs.
   - No integrity violations found in `backend/dom_parser.py` or `backend/security_isolation.py`.

---

## 2. Logic Chain

1. **Test Suite Failure**:
   - The test suite `backend/tests/test_dom_parser_adversarial.py` contains a test `test_multiple_urls_in_css_background` where the assertion expects `obj_id` to be `None` when `style` has `linear-gradient(...)`.
   - Because `linear-gradient` does not match `url(...)`, `re.search` skips `linear-gradient` and matches `url('/remote/v1/obj_attachment?obj=vid777')`.
   - `extract_obj_id_from_url_or_style` returns `obj_id = 'vid777'`, causing `assert obj_id is None` to fail.
   - Independent of the test flaw, this revealed that `extract_obj_id_from_url_or_style` relies on simplistic `re.search(r'url\(...')` which breaks when CSS has case variations or multiple `url(...)` targets.

2. **Timeframe Link Parsing Flaw**:
   - `is_valid_timeframe_text` relies solely on `^[a-z]{3}\s+\d{4}$`.
   - Any 3-letter string (e.g. `"cat 2025"`, `"all 2026"`) passes validation.
   - `months_map.get("all", 1)` falls back to month 1 (January).
   - This can cause non-month navigation tiles or UI text to be wrongly parsed as January timeframe links.

3. **Date Overlay Parsing Fallback Flaw**:
   - `parse_date_overlay` only handles numeric slash formats (`M/D` and `M/D/Y`).
   - If Bright Horizons UI presents textual date labels (e.g. "Jun 22, 2026") or relative strings ("Today", "Yesterday") in post footers, `parse_date_overlay` silently defaults to `now.month` and `now.day`.
   - If a photo was taken on June 15, 2024, but scraped today (July 31, 2026), it gets tagged as `2024-07-31` instead of `2024-06-15`.

4. **Security & Isolation Architecture Conformance**:
   - `backend/security_isolation.py` strictly follows all requirements specified in `PROJECT.md` and `AGENTS.md`.
   - Lock purging, path canonicalization, credential masking, and child output scoping are fully robust and well-tested.

---

## 3. Caveats

- **Browser DOM Integration**: Mock tests confirm Playwright locator queries for Knockout.js and Angular CDK overlays work in simulated structures. Live browser execution depends on actual Bright Horizons portal availability.
- **Pipeline Handoff**: `backend/pipeline.py` (Milestone 2) and `backend/multi_tenant.py` (Milestone 3) are not yet implemented. This review is limited to Milestone 1 modules (`dom_parser.py` and `security_isolation.py`).

---

## 4. Conclusion

### Review Summary & Verdict

**Verdict**: **REQUEST_CHANGES**

### Summary of Findings

| Severity | Location | Issue | Suggested Fix |
|----------|----------|-------|---------------|
| **Major** | `backend/tests/test_dom_parser_adversarial.py:218` | `pytest` test suite execution fails with 1 test assertion error in `test_multiple_urls_in_css_background`. | Correct test string/assertion mismatch in `test_dom_parser_adversarial.py` and update `extract_obj_id_from_url_or_style` to robustly search for `obj_attachment` or `obj=` across all `url(...)` CSS occurrences. |
| **Major** | `backend/dom_parser.py:20, 118` | `TIMEFRAME_REGEX` matches non-month 3-letter words (e.g., `"foo 2026"`, `"all 2026"`), which default to month 1 (January). | Update `TIMEFRAME_REGEX` to validate against valid month abbreviations (`jan|feb|mar|...`) or check `if month_name in months_map`. |
| **Major** | `backend/dom_parser.py:32-64` | `parse_date_overlay` falls back to `now.month` and `now.day` for non-slash date strings ("Jun 15, 2026", "Today", "Yesterday", ISO dates) and allows out-of-range dates ("99/99"). | Expand date overlay parser to handle textual month names, ISO dates, relative dates, and validate month/day ranges. |
| **Minor** | `backend/dom_parser.py:82` | `extract_obj_id_from_url_or_style` uses case-sensitive `url(...)` regex and misclassifies photo hrefs without `obj_attachment` as videos. | Add `re.IGNORECASE` to CSS URL regex, and check `obj=` or attachment parameters when classifying media types. |

### Verified Claims

- `backend/security_isolation.py` unit tests pass 100% (14/14 tests) → verified via `pytest` → PASS
- Lock file cleaning (`clean_user_data_locks`) unlinks Chromium locks → verified via `test_clean_user_data_locks` → PASS
- Isolated user data cloning excludes singleton locks → verified via `test_prepare_isolated_user_data` → PASS
- Path traversal & null byte injection blocked → verified via `test_canonicalize_and_validate_path_traversal` → PASS
- Sensitive credentials & MFA codes redacted → verified via `test_mask_sensitive_data` → PASS
- `extract_feed_items` strictly scoped inside `div.well.left-panel.pull-left` → verified via `test_extract_feed_items_scoping_mock` → PASS

### Security & Integrity Assessment
- **Integrity Violations**: None found (0 critical integrity issues).
- **Security Isolation Quality**: Excellent.

---

## 5. Verification Method

To independently verify this review assessment, run the following commands:

```bash
# 1. Run unit test suite to observe test failure
.venv/bin/pytest backend/tests/ -v

# 2. Run specific dom parser tests
.venv/bin/pytest backend/tests/test_dom_parser.py -v
.venv/bin/pytest backend/tests/test_dom_parser_adversarial.py -v

# 3. Run security isolation tests
.venv/bin/pytest backend/tests/test_security_isolation.py -v
```

**Invalidation Conditions**:
- If `.venv/bin/pytest backend/tests/ -v` passes with 0 failures after fixing the test and `dom_parser.py` issues, the REQUEST_CHANGES verdict can be upgraded to APPROVE.
