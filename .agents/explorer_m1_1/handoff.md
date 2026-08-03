# Handoff Report — Explorer M1.1: DOM Parsing Specifications & Design

## 1. Observation
1. **Repository Rules & Specs**:
   - `file:///home/antigravity/GitHub/brighthorizon-photo-extractor/.agents/AGENTS.md` (lines 14-46, 60-100) specifies:
     - Section 2.A: Timeframe month link text matching `^[a-z]{3}\s+\d{4}$` on `li`, Knockout click binding on inner `div.tile` (`div.tile.pointable`).
     - Section 2.B: Feed media items scope inside `div.well.left-panel.pull-left` to avoid collision with `.thumbnails` child selection buttons.
     - Section 2.C: Photo posts use `a.fancybox` href with `obj_attachment`, while Video posts use fragment hrefs (`#...`) requiring thumbnail `style` parsing on `div.tile.pointable`.
     - Section 5: Child auto-discovery on `familyinfocenter.brighthorizons.com/home` requires finding `h1` full names, clicking `span.actions-menu-item-label` for Actions dropdown, selecting `span.actions-menu-item-label` with "My Bright Day", and expecting new tab context for `dependent_id`.
2. **Current Implementation in `scraper_engine.py`**:
   - `file:///home/antigravity/GitHub/brighthorizon-photo-extractor/backend/scraper_engine.py`:
     - Lines 679-739 (`discover_children`): Iterates over `actions_spans`, clicks triggers without CDK backdrop error handling/dismissal when skipping non-enrolled children.
     - Lines 765-777 & 790-805 (`extract_child_feed` timeframe handling): Uses `re.search(r'[a-z]{3}\s+\d{4}', ...)` without anchors, stores snapshot array `timeframe_lis = page.locator("li").all()`, leading to Playwright stale element handles across DOM re-renders.
     - Lines 811-814 (`extract_child_feed` feed container scoping): `feed_items = timeline.locator("ul.thumbnails li").all() if timeline.count() > 0 else page.locator("ul.thumbnails li").all()`. Global fallback risks matching top navigation bar child buttons.
     - Lines 823-875 (`extract_child_feed` item parsing): Duplicate date parsing logic, raw URL regex without HTML unescaping (`&amp;`), no explicit media type classification.

---

## 2. Logic Chain
1. **Observation 1 & 2 -> Feed Container Scoping**: `scraper_engine.py` line 813 falls back to `page.locator("ul.thumbnails li").all()` if `timeline.count() == 0`. Per AGENTS.md Section 2.B, global `.thumbnails` querying matches top bar child selector elements. Therefore, `dom_parser.py` must strictly query `div.well.left-panel.pull-left` and return empty if absent.
2. **Observation 1 & 2 -> Timeframe Month Panel**: Storing a list of `ElementHandle` objects (`timeframe_lis`) and calling `.click()` on them sequentially fails in Playwright when DOM re-renders occur between iterations. Therefore, `dom_parser.py` must use dynamic text-based locators or re-evaluate fresh locators per iteration, and strictly target `div.tile.pointable` per Section 2.A.
3. **Observation 1 & 2 -> Video Media Link Parsing**: Fragment hrefs (`#...`) indicate video posts. Extracted inline styles contain HTML entities (`&amp;`). Therefore, `dom_parser.py` must unescape HTML entities and resolve `obj_id` safely via pure testable helper functions.
4. **Observation 1 & 2 -> Angular CDK Overlay**: In `discover_children`, timing out on non-enrolled children leaves Angular CDK overlay backdrops open, causing subsequent click attempts to fail. Therefore, `dom_parser.py` must include `dismiss_cdk_overlays` cleanup.

---

## 3. Caveats
- **Live DOM Testing**: Analysis and proposed design are based on static analysis of `AGENTS.md` and `scraper_engine.py`. Live browser verification depends on Playwright runtime execution in implementation milestones.
- **Pure Helpers**: Pure string/regex helpers (`is_valid_timeframe_text`, `extract_obj_id_from_url_or_style`, `parse_post_date`) can be unit tested without browser instances.

---

## 4. Conclusion
The proposed `backend/dom_parser.py` architecture cleanly isolates DOM parsing, fixes 4 critical flaws (stale element handles, global thumbnail fallback pollution, video URL entity escaping, CDK overlay lockups), and provides a fully specified, unit-testable module for implementers.

---

## 5. Verification Method
1. **Inspect Analysis Report**:
   - View `/home/antigravity/GitHub/brighthorizon-photo-extractor/.agents/explorer_m1_1/analysis.md`.
2. **Run Existing Test Suite**:
   - `pytest /home/antigravity/GitHub/brighthorizon-photo-extractor/backend/tests/test_security.py`
3. **Future Verification of `backend/dom_parser.py` Implementation**:
   - When implemented, verify via `pytest backend/tests/test_dom_parser.py`.
