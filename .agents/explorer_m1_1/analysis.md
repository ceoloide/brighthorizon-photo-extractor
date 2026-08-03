# Technical Analysis & Architectural Design: DOM Parsing Module (`backend/dom_parser.py`)

## Executive Summary
This analysis evaluates DOM parsing specifications across the **My Bright Day** parent portal (`mybrightday.brighthorizons.com`) and **Family Info Center** (`familyinfocenter.brighthorizons.com`) based on `.agents/AGENTS.md` and `backend/scraper_engine.py`. 

Currently, `backend/scraper_engine.py` contains monolithic Playwright logic where DOM selector queries, element iterations, state waits, regex parsing, and network downloads are tightly coupled. This investigation analyzes 4 specific DOM parsing requirement areas, identifies critical bugs and architectural pitfalls in the current implementation, and provides a comprehensive design for a dedicated, modular `backend/dom_parser.py` package.

---

## 1. Deep Analysis of Focus Areas

### 1.1 Focus Area 1: Feed Container Scoping (`div.well.left-panel.pull-left`)

#### Specification & Context
Per `AGENTS.md` Section 2.B:
- Both the horizontal top child selector bar (containing buttons for "Byron", "Catherine", "All Kids") and the timeline media listings use the `.thumbnails` CSS class (`<ul class="thumbnails">`).
- Executing a global DOM search like `document.querySelectorAll('ul.thumbnails li')` returns both child navigation elements and feed post elements.
- **Rule**: Timeline searches MUST be strictly scoped inside the main content well: `div.well.left-panel.pull-left`.

#### Existing Implementation Analysis (`backend/scraper_engine.py` lines 811-814)
```python
# Scope timeline search inside left panel (rule 2.B in AGENTS.md)
timeline = page.locator("div.well.left-panel.pull-left")
feed_items = timeline.locator("ul.thumbnails li").all() if timeline.count() > 0 else page.locator("ul.thumbnails li").all()
```

#### Flaws & Pitfalls Identified
1. **Unsafe Fallback to Global Match**:
   - If `timeline.count() == 0` (which can occur during page rendering, tab switches, or network lag before Knockout.js binds the left panel), the ternary expression falls back to `page.locator("ul.thumbnails li").all()`.
   - This fallback directly violates Rule 2.B by querying all global `.thumbnails li` elements, selecting top navigation child filter buttons as feed items.
   - Processing child filter buttons as feed items causes item parsing failures, duplicate log noise, or invalid obj_id extraction attempts.
2. **Missing Visibility / Render Wait**:
   - `timeline.count()` checks immediate DOM presence without waiting for the timeline element to be attached or visible.
   - A robust DOM parser must explicitly wait for `div.well.left-panel.pull-left` to be present and populated before querying feed items.

---

### 1.2 Focus Area 2: Timeframe Month Panel Handling (`^[a-z]{3}\s+\d{4}$`, inner `div.tile` click)

#### Specification & Context
Per `AGENTS.md` Section 2.A:
- Month links inside the timeframe sidebar match text pattern `^[a-z]{3}\s+\d{4}$` (case-insensitive, e.g., `jun 2026`).
- Knockout.js attaches its `click: select` binding to the inner `div.tile` child element (`div.tile.pointable`).
- **Rule**: Clicking the outer `<li>` element directly does **not** trigger Knockout event handlers or reload the timeline feed.

#### Existing Implementation Analysis (`backend/scraper_engine.py` lines 765-777 & 790-805)
```python
# Finding timeframe links
timeframe_lis = []
start_wait = time.time()
while time.time() - start_wait < 45.0:
    try:
        lis = page.locator("li").all()
        matching = [li for li in lis if re.search(r'[a-z]{3}\s+\d{4}', li.inner_text().strip(), re.IGNORECASE)]
        if matching:
            timeframe_lis = matching
            break
    except Exception:
        pass
    time.sleep(1.0)

# Iterating and clicking month links
for tf_li in timeframe_lis:
    tf_text = tf_li.inner_text().strip()
    tile = tf_li.locator("div.tile.pointable").first
    if tile.count() > 0:
        tile.click()
    else:
        tf_li.click()
    page.wait_for_timeout(3000)
```

#### Flaws & Pitfalls Identified
1. **Stale Element Handle Exception (Playwright Bug)**:
   - `page.locator("li").all()` evaluates all `<li>` elements and returns a fixed snapshot of `ElementHandle` objects (`timeframe_lis`).
   - In the loop, clicking `tile.click()` triggers Knockout.js AJAX requests and re-renders the DOM.
   - On subsequent iterations, references inside `timeframe_lis` become **stale** (detached DOM nodes). Attempting to call `.inner_text()` or `.locator()` on subsequent stale handles raises Playwright `ElementHandle.click: Element is not attached to the DOM` or silently fails.
2. **Regex Lack of Anchors**:
   - `re.search(r'[a-z]{3}\s+\d{4}', ...)` matches substrings without boundary anchors. Text such as `"Selected Nov 2024 (12 items)"` would match unexpectedly.
   - The regex should use exact anchors: `^[a-z]{3}\s+\d{4}$` (after stripping whitespace).
3. **Ineffective Outer `<li>` Fallback**:
   - `tf_li.click()` is attempted if `tile.count() == 0`. Per `AGENTS.md`, clicking `<li>` does not trigger Knockout feed reloads. If `div.tile` or `div.tile.pointable` is missing, the fallback fails silently without loading the month's posts.

---

### 1.3 Focus Area 3: Media Link Parsing (`a.fancybox` vs `div.tile.pointable` style)

#### Specification & Context
Per `AGENTS.md` Section 2.C:
- **Photos**: `<a class="fancybox">` element contains an `href` matching `/remote/v1/obj_attachment?obj=<OBJ_ID>...`.
- **Videos**: `<a class="fancybox">` has an `href` pointing to a local DOM fragment indicator (e.g., `href="#6986168d2bb117b0dc910b3b-default"`).
- **Rule for Videos**: When `href` starts with `#` or lacks `obj_attachment`, the scraper must read the CSS `style` attribute from `div.tile.pointable` (or child container) to extract the attachment URL pattern `url('...')`.

#### Existing Implementation Analysis (`backend/scraper_engine.py` lines 823-875)
```python
fancybox = item.locator("a.fancybox").first
if fancybox.count() == 0:
    continue

href = fancybox.get_attribute("href") or ""

# Video post handling (rule 2.C in AGENTS.md)
if href.startswith("#") or "obj_attachment" not in href:
    pointable_tile = item.locator("div.tile.pointable").first
    style = pointable_tile.get_attribute("style") or "" if pointable_tile.count() > 0 else ""
    match = re.search(r'url\([\'"]?([^\'"]+)[\'"]?\)', style)
    if match:
        href = match[1]

m_obj = re.search(r'obj=([^&]+)', href)
if not m_obj:
    continue
obj_id = m_obj.group(1)

# Lines 853-856 AND 869-870: Duplicate code block for date overlay parsing
overlay_span = item.locator("span.name span").first
date_text = overlay_span.inner_text().strip() if overlay_span.count() > 0 else ""
date_str = parse_date(date_text, tf_text)
```

#### Flaws & Pitfalls Identified
1. **Duplicate Executed Code**:
   - `overlay_span` and `parse_date` logic is executed twice per loop iteration (lines 853-856 and 869-870).
2. **HTML Entity & URL Escaping Hazards**:
   - Extraction of `href` from `style="background-image: url('/remote/v1/obj_attachment?obj=123&amp;key=123')"` may yield HTML-encoded entity `&amp;`.
   - `re.search(r'obj=([^&]+)', href)` works if `&` is raw, but if `href` contains `&amp;`, `obj_id` regex match `([^&]+)` might stop at `&` (yielding `123`), but if unescaped parameter string has different formatting, it could include `amp;` noise.
3. **No Explicit Media Type Tagging**:
   - The current parser does not classify whether an item is a `photo` or `video` during extraction. Classifying this upstream allows setting accurate MIME types and extensions.

---

### 1.4 Focus Area 4: Angular CDK Overlay Dropdown Parsing in `discover_children`

#### Specification & Context
Per `AGENTS.md` Section 5:
- Target page: `familyinfocenter.brighthorizons.com/home` (Angular application).
- Each child profile card contains an `<h1>` heading with full name (e.g. `Byron Taccani Massarelli`).
- Trigger: `<span class="actions-menu-item-label">` inside the Actions menu trigger button — **NOT a `<button>` tag**.
- Dropdown menu: Dynamically rendered into Angular's global CDK overlay container (`div.cdk-overlay-container`) ONLY after clicking the Actions span.
- Target menu item: `span.actions-menu-item-label` matching text `"My Bright Day"`.
  - *Pitfall*: Do NOT use `page.locator("text=My Bright Day")` because it matches promotional `<h4>` footer banners.
- Navigation target: Opens a new browser tab with URL format:
  `https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id=<DEPENDENT_ID>`
- Children without active enrollment do not display the "My Bright Day" menu item.

#### Existing Implementation Analysis (`backend/scraper_engine.py` lines 679-739)
```python
actions_spans = page.locator("span", has_text="Actions").all()
for idx, span in enumerate(actions_spans):
    try:
        card_name = span.evaluate("""(el) => {
            let current = el;
            while (current && current.tagName !== 'BODY') {
                let h1 = current.querySelector('h1');
                if (h1 && h1.textContent.trim()) return h1.textContent.trim();
                current = current.parentElement;
            }
            return '';
        }""")
        ...
        span.click()
        page.wait_for_timeout(1000)
        
        mbd = page.locator("span.actions-menu-item-label", has_text="My Bright Day").first
        mbd.wait_for(state="visible", timeout=3000)
        
        with context.expect_page() as new_page_info:
            mbd.evaluate("(el) => (el.closest('a') || el.closest('button') || el).click()")
        new_page = new_page_info.value
        ...
```

#### Flaws & Pitfalls Identified
1. **CDK Overlay Backdrop Stacking / Lockup on Inactive Children**:
   - When `span.click()` opens an Angular CDK dropdown for a child without active enrollment, `mbd.wait_for(state="visible", timeout=3000)` times out and throws an exception.
   - The Angular CDK overlay backdrop remains open on screen!
   - On the next loop iteration, clicking the next child's `Actions` span will fail or hit the backdrop element (`div.cdk-overlay-backdrop`).
   - **Fix**: In `except` blocks or cleanup steps, explicitly dismiss active CDK overlays (e.g. `page.keyboard.press("Escape")` or clicking backdrop).
2. **Ambiguous `span:has-text('Actions')` Locator**:
   - `page.locator("span", has_text="Actions")` is un-scoped and could match header menu buttons or toolbar actions. Scoping `Actions` spans to child cards prevents false matches.

---

## 2. Proposed Module Design for `backend/dom_parser.py`

To eliminate these bugs, decouple selector logic, and enable unit testing, we design `backend/dom_parser.py` as a robust, pure & Playwright-compatible DOM parsing layer.

### 2.1 Key Design Principles
1. **Clean Object Models (Dataclasses)**:
   - `ChildProfile`: Represents child metadata (`name`, `given_name`, `full_name`, `dependent_id`).
   - `TimeframeMonth`: Represents month panel entry (`raw_text`, `month_name`, `year`, `formatted_month`).
   - `FeedItemData`: Standardized post metadata (`obj_id`, `media_type`, `date_str`, `date_text`, `download_url`, `is_video`, `raw_href`).
2. **Fresh Locator Evaluation (Avoiding Stale Handles)**:
   - Store selector strings or index-based retrieval methods rather than caching raw Playwright `ElementHandle` arrays across DOM re-renders.
3. **Pure String & HTML Helper Functions**:
   - Extract regex parsing (`extract_obj_id`, `extract_url_from_style`, `match_timeframe_pattern`, `parse_date_text`) into standalone pure functions so they can be unit-tested without browser instances.
4. **Resilient Playwright Action Handlers**:
   - Safe CDK overlay dismissal.
   - Strict container scoping.

---

### 2.2 Complete Code Specification for `backend/dom_parser.py`

```python
# SPDX-License-Identifier: MIT
# DOM Parser & Selector Abstraction for Bright Horizons Portals
import re
import html
from dataclasses import dataclass
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple
from playwright.sync_api import Page, BrowserContext, Locator, ElementHandle

# -----------------------------------------------------------------------------
# Data Models
# -----------------------------------------------------------------------------

@dataclass
class ChildProfile:
    name: str           # e.g., "Byron"
    given_name: str     # e.g., "Byron"
    full_name: str      # e.g., "Byron Taccani Massarelli"
    dependent_id: str   # e.g., "673e065a9d37c9fab2483b2d"


@dataclass
class TimeframeMonth:
    raw_text: str       # e.g., "jun 2026"
    month_name: str     # e.g., "jun"
    year: int           # e.g., 2026


@dataclass
class FeedItemData:
    obj_id: str         # e.g., "6986168d2bb117b0dc910b3b"
    media_type: str     # "photo" or "video"
    date_str: str       # YYYY-MM-DD format, e.g. "2026-06-15"
    date_text: str      # Raw overlay text, e.g. "6/15"
    download_url: str   # Full attachment URL
    is_video: bool      # True if video post
    raw_href: str       # Raw href extracted from DOM


# -----------------------------------------------------------------------------
# Pure Helper Functions (Unit-Testable without Browser)
# -----------------------------------------------------------------------------

TIMEFRAME_REGEX = re.compile(r'^[a-z]{3}\s+\d{4}$', re.IGNORECASE)

def is_valid_timeframe_text(text: str) -> bool:
    """Checks if cleaned text matches timeframe pattern ^[a-z]{3}\\s+\\d{4}$ (rule 2.A)."""
    return bool(TIMEFRAME_REGEX.match(text.strip()))


def parse_timeframe_string(text: str) -> Optional[TimeframeMonth]:
    """Parses month name and year from timeframe text (e.g. 'jun 2026')."""
    clean_text = text.strip()
    if not is_valid_timeframe_text(clean_text):
        return None
    parts = clean_text.split()
    return TimeframeMonth(
        raw_text=clean_text,
        month_name=parts[0].lower(),
        year=int(parts[1])
    )


def extract_url_from_style(style_attr: str) -> Optional[str]:
    """Extracts background image URL from element inline style attribute (rule 2.C)."""
    if not style_attr:
        return None
    # Unescape HTML entities first (e.g., &amp; -> &)
    style_clean = html.unescape(style_attr)
    match = re.search(r'url\([\'"]?([^\'"]+)[\'"]?\)', style_clean)
    if match:
        return match.group(1).strip()
    return None


def extract_obj_id_from_url_or_style(href: str, style: str) -> Tuple[Optional[str], bool, str]:
    """
    Parses obj_id, video indicator, and raw attachment path from fancybox href or tile style.
    Returns: (obj_id, is_video, resolved_url)
    """
    href_clean = html.unescape(href.strip()) if href else ""
    style_clean = html.unescape(style.strip()) if style else ""
    
    is_video = False
    resolved_url = href_clean

    # Rule 2.C: If href starts with '#' or lacks obj_attachment, it's a video post
    if href_clean.startswith("#") or "obj_attachment" not in href_clean:
        is_video = True
        style_url = extract_url_from_style(style_clean)
        if style_url:
            resolved_url = style_url

    # Extract obj ID parameter
    match = re.search(r'obj=([^&]+)', resolved_url)
    if match:
        return match.group(1), is_video, resolved_url

    return None, is_video, resolved_url


def parse_post_date(date_text: str, timeframe_text: str) -> str:
    """Parses date string into YYYY-MM-DD format using timeframe year context."""
    now = datetime.now()
    tf_year = None
    if timeframe_text:
        m_tf = re.search(r'\b(20\d{2})\b', timeframe_text)
        if m_tf:
            tf_year = int(m_tf.group(1))

    clean_text = date_text.strip() if date_text else ""
    if not clean_text:
        year_val = tf_year or now.year
        return f"{year_val:04d}-{now.month:02d}-{now.day:02d}"

    m = re.search(r'(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?', clean_text)
    if m:
        month, day, year = m.groups()
        if not year:
            year = tf_year or now.year
        else:
            year = int(year)
            if year < 100:
                year += 2000
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"

    year_val = tf_year or now.year
    return f"{year_val:04d}-{now.month:02d}-{now.day:02d}"


# -----------------------------------------------------------------------------
# Family Info Center DOM Parser
# -----------------------------------------------------------------------------

class FamilyInfoCenterParser:
    """Encapsulates DOM navigation for familyinfocenter.brighthorizons.com."""

    ACTIONS_SPAN_SELECTOR = "span.actions-menu-item-label, span"
    MBD_DROPDOWN_SELECTOR = "span.actions-menu-item-label"
    CDK_OVERLAY_CONTAINER = "div.cdk-overlay-container"

    @staticmethod
    def dismiss_cdk_overlays(page: Page):
        """Dismisses open Angular CDK dropdown overlays/backdrops cleanly."""
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
        except Exception:
            pass

    @classmethod
    def discover_children(cls, page: Page, context: BrowserContext, logger=None) -> List[ChildProfile]:
        """Discovers enrolled children using Angular CDK overlay rules (AGENTS.md Section 5)."""
        log = logger or (lambda msg: None)
        children: List[ChildProfile] = []

        page.goto("https://familyinfocenter.brighthorizons.com/home", wait_until="domcontentloaded")
        try:
            page.wait_for_selector("span:has-text('Actions')", timeout=15000)
        except Exception:
            pass
        page.wait_for_timeout(2000)

        # Find all Actions menu triggers
        actions_spans = page.locator("span", has_text="Actions").all()
        log(f"Found {len(actions_spans)} 'Actions' triggers on child cards.")

        for idx, span in enumerate(actions_spans):
            try:
                # Find child full name from h1 in parent card container
                card_name = span.evaluate("""(el) => {
                    let current = el;
                    while (current && current.tagName !== 'BODY') {
                        let h1 = current.querySelector('h1');
                        if (h1 && h1.textContent.trim()) return h1.textContent.trim();
                        current = current.parentElement;
                    }
                    return '';
                }""")

                if not card_name:
                    continue

                full_name = card_name.strip()
                given_name = full_name.split()[0].capitalize()

                # Click Actions trigger to open CDK overlay
                span.click()
                page.wait_for_timeout(800)

                # Locate specific "My Bright Day" menu item (Rule 5: span.actions-menu-item-label)
                mbd_item = page.locator(cls.MBD_DROPDOWN_SELECTOR, has_text="My Bright Day").first
                
                try:
                    mbd_item.wait_for(state="visible", timeout=3000)
                except Exception:
                    # Child is not enrolled (Rule 5) - dismiss CDK overlay and skip
                    log(f"Child '{given_name}' has no active My Bright Day enrollment. Skipping.")
                    cls.dismiss_cdk_overlays(page)
                    continue

                # Expect new page tab navigation
                with context.expect_page() as new_page_info:
                    mbd_item.evaluate("(el) => (el.closest('a') || el.closest('button') || el).click()")

                new_page = new_page_info.value
                new_page.wait_for_load_state("domcontentloaded", timeout=10000)

                match = re.search(r'dependent_id=([^&]+)', new_page.url)
                if match:
                    dep_id = match.group(1)
                    profile = ChildProfile(
                        name=given_name,
                        given_name=given_name,
                        full_name=full_name,
                        dependent_id=dep_id
                    )
                    children.append(profile)
                    log(f"Discovered child: {given_name} (dependent_id: {dep_id[:8]}...)")

                new_page.close()

            except Exception as err:
                log(f"Skipped child card #{idx + 1}: {err}")
                cls.dismiss_cdk_overlays(page)

        return children


# -----------------------------------------------------------------------------
# My Bright Day Portal DOM Parser
# -----------------------------------------------------------------------------

class MyBrightDayParser:
    """Encapsulates DOM navigation for mybrightday.brighthorizons.com dashboard."""

    TIMELINE_WELL_SELECTOR = "div.well.left-panel.pull-left"
    TIMEFRAME_LI_SELECTOR = "li"
    INNER_TILE_SELECTOR = "div.tile.pointable, div.tile"
    FEED_ITEM_SELECTOR = "ul.thumbnails li"

    @classmethod
    def get_timeline_container(cls, page: Page) -> Optional[Locator]:
        """Strictly locates main timeline container (Rule 2.B). Returns None if absent."""
        container = page.locator(cls.TIMELINE_WELL_SELECTOR)
        if container.count() > 0:
            return container.first
        return None

    @classmethod
    def get_timeframe_month_texts(cls, page: Page, timeout_sec: float = 45.0) -> List[str]:
        """
        Polls DOM until Knockout.js timeframe month links load (Rule 2.A).
        Returns matching month strings matching ^[a-z]{3}\\s+\\d{4}$.
        """
        start_time = datetime.now()
        matching_texts: List[str] = []

        while (datetime.now() - start_time).total_seconds() < timeout_sec:
            try:
                lis = page.locator(cls.TIMEFRAME_LI_SELECTOR).all()
                found = []
                for li in lis:
                    txt = li.inner_text().strip()
                    if is_valid_timeframe_text(txt):
                        found.append(txt)
                if found:
                    matching_texts = found
                    break
            except Exception:
                pass
            page.wait_for_timeout(1000)

        return matching_texts

    @classmethod
    def select_timeframe_month(cls, page: Page, month_text: str) -> bool:
        """
        Dynamically locates matching timeframe li and clicks inner div.tile target (Rule 2.A).
        Avoids stale element references by evaluating fresh locators.
        """
        # Find matching li by text
        lis = page.locator(cls.TIMEFRAME_LI_SELECTOR).all()
        for li in lis:
            if li.inner_text().strip().lower() == month_text.strip().lower():
                # Rule 2.A: Knockout click binding is on inner div.tile
                tile = li.locator(cls.INNER_TILE_SELECTOR).first
                if tile.count() > 0:
                    tile.click()
                    return True
                else:
                    # Fallback to direct click if tile not found
                    li.click()
                    return True
        return False

    @classmethod
    def extract_feed_items(cls, page: Page) -> List[Locator]:
        """
        Strictly scopes feed media posts inside div.well.left-panel.pull-left (Rule 2.B).
        Prevents matching top child selector buttons.
        """
        timeline = cls.get_timeline_container(page)
        if timeline is not None:
            return timeline.locator(cls.FEED_ITEM_SELECTOR).all()
        # Strictly return empty list if timeline panel is absent (do NOT fall back to global thumbnails!)
        return []

    @classmethod
    def parse_feed_item(cls, item: Locator, timeframe_text: str) -> Optional[FeedItemData]:
        """Parses a single feed item locator into FeedItemData (Rule 2.C)."""
        fancybox = item.locator("a.fancybox").first
        if fancybox.count() == 0:
            return None

        raw_href = fancybox.get_attribute("href") or ""
        
        pointable_tile = item.locator(cls.INNER_TILE_SELECTOR).first
        style_attr = pointable_tile.get_attribute("style") or "" if pointable_tile.count() > 0 else ""

        obj_id, is_video, resolved_url = extract_obj_id_from_url_or_style(raw_href, style_attr)
        if not obj_id:
            return None

        # Parse date overlay
        overlay_span = item.locator("span.name span").first
        date_text = overlay_span.inner_text().strip() if overlay_span.count() > 0 else ""
        date_str = parse_post_date(date_text, timeframe_text)

        download_url = f"https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj={obj_id}&key={obj_id}"
        media_type = "video" if is_video else "photo"

        return FeedItemData(
            obj_id=obj_id,
            media_type=media_type,
            date_str=date_str,
            date_text=date_text,
            download_url=download_url,
            is_video=is_video,
            raw_href=raw_href
        )
```

---

## 3. Recommended Unit Tests for `backend/tests/test_dom_parser.py`

To ensure 100% test coverage for `backend/dom_parser.py`, unit tests should cover:

1. **`test_is_valid_timeframe_text`**:
   - Valid inputs: `"jun 2026"`, `"NOV 2024"`, `"  dec 2025  "`
   - Invalid inputs: `"Jun 2026 (12 items)"`, `"All Months"`, `"2026"`, `""`
2. **`test_extract_url_from_style`**:
   - CSS style strings: `"background-image: url('/remote/v1/obj_attachment?obj=123');"`
   - Unescaping HTML entities: `"background-image: url('/remote/v1/obj_attachment?obj=123&amp;key=123');"`
3. **`test_extract_obj_id_from_url_or_style`**:
   - Photo post (`href="/remote/v1/obj_attachment?obj=abc123"`): returns `("abc123", False, ...)`
   - Video post (`href="#abc123-default"`, `style="background-image: url('/remote/v1/obj_attachment?obj=def456')"`): returns `("def456", True, ...)`
4. **`test_parse_post_date`**:
   - Standard `"6/15"` with `timeframe_text="jun 2026"` -> `"2026-06-15"`
   - Full date string `"11/24/2025"` -> `"2025-11-24"`
5. **`test_mybrightday_parser_strict_feed_scoping`**:
   - Mock page locator where `div.well.left-panel.pull-left` is absent: verifies `extract_feed_items` returns `[]` without querying global page thumbnails.

---

## 4. Verification & Handoff Summary
- **Evidence Sources**: `AGENTS.md` Sections 2.A, 2.B, 2.C, 5; `backend/scraper_engine.py` lines 679-739, 765-805, 811-875.
- **Architectural Value**: Transitioning DOM parsing logic from inline code in `scraper_engine.py` into `backend/dom_parser.py` resolves 4 critical bugs (stale DOM handles, dangerous fallback thumbnail matches, unescaped video URLs, CDK backdrop lockups) while enabling unit tests.
