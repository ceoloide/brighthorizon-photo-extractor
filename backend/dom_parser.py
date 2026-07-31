# SPDX-License-Identifier: MIT
"""
DOM Parser Module for Bright Horizons Photo Extractor.

Encapsulates all Playwright DOM queries, Knockout.js month navigation,
feed element extraction, video background fallback parsing, and Angular CDK auto-discovery.
Spec reference: .agents/explorer_m1_1/analysis.md & .agents/explorer_m1_3/analysis.md
"""

import re
import html
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from playwright.sync_api import Page, BrowserContext, Locator

# -----------------------------------------------------------------------------
# Pure Helper Utilities (Unit Testable without Browser)
# -----------------------------------------------------------------------------

VALID_MONTH_ABBRS = r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)'
TIMEFRAME_REGEX = re.compile(rf'^{VALID_MONTH_ABBRS}\s+\d{{4}}$', re.IGNORECASE)

def is_valid_timeframe_text(text: str) -> bool:
    r"""
    Checks if text matches timeframe pattern ^(jan|feb|...)\s+\d{4}$ (Rule 2.A).
    Case-insensitive, strictly validating 3-letter month abbreviations.
    Stripped of leading/trailing whitespace.
    """
    if not text or not isinstance(text, str):
        return False
    return bool(TIMEFRAME_REGEX.match(text.strip()))


def get_month_end_date(tf_text: str) -> Optional[str]:
    """
    Returns the last day of the month as 'YYYY-MM-DD' string for a timeframe text like 'may 2026'.
    """
    if not tf_text or not isinstance(tf_text, str):
        return None
    try:
        parts = tf_text.strip().split()
        if len(parts) >= 2:
            m_str, y_str = parts[0].lower(), parts[1]
            month_map = {
                "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
            }
            m_num = month_map.get(m_str[:3])
            year = int(y_str)
            if m_num and year:
                if m_num in [1, 3, 5, 7, 8, 10, 12]:
                    last_day = 31
                elif m_num in [4, 6, 9, 11]:
                    last_day = 30
                else:
                    last_day = 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28
                return f"{year:04d}-{m_num:02d}-{last_day:02d}"
    except Exception:
        pass
    return None


def parse_date_overlay(date_text: str, timeframe_year: Optional[int] = None) -> str:
    """
    Parses date overlay text into ISO date format 'YYYY-MM-DD'.
    Handles formats like:
      - Numerical M/D, M/D/Y, MM/DD/YYYY, M/D/Y with time ('6/15', '06/15/2026', '6/15/26', '6/15/2026 10:00 AM')
      - ISO dates ('2026-06-15', '2026/06/15', '2026.06.15')
      - Textual month dates ('Jun 15, 2026', 'June 15', '15 Jun 2026')
      - Relative dates ('Today', 'Yesterday')
      - Separators with dots or dashes ('06.15.2026', '6-15-2026')
    Enforces strict month (1-12) and day (1-31) range checking.
    Contextualizes missing year using timeframe_year or current year.
    """
    now = datetime.now()
    default_year = timeframe_year or now.year
    fallback_date = f"{default_year:04d}-{now.month:02d}-{now.day:02d}"

    if not date_text or not isinstance(date_text, str):
        return fallback_date

    clean_text = date_text.strip()
    if not clean_text:
        return fallback_date

    lower_text = clean_text.lower()

    # Relative date handling
    if lower_text == "today":
        return f"{default_year:04d}-{now.month:02d}-{now.day:02d}"
    if lower_text == "yesterday":
        yest = now - timedelta(days=1)
        y_year = timeframe_year or yest.year
        return f"{y_year:04d}-{yest.month:02d}-{yest.day:02d}"

    def _valid_iso_date(year: int, month: int, day: int) -> Optional[str]:
        if 1 <= month <= 12 and 1 <= day <= 31:
            if year < 100:
                year += 2000
            return f"{year:04d}-{month:02d}-{day:02d}"
        return None

    # 1. ISO format: YYYY-MM-DD or YYYY/MM/DD or YYYY.MM.DD (with optional time)
    m_iso = re.match(r'^(\d{4})[-/\.]([01]?\d)[-/\.]([0-3]?\d)(?:\s+.*)?$', clean_text)
    if m_iso:
        res = _valid_iso_date(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)))
        return res if res else fallback_date

    # 2. M/D/Y (4-digit or 2-digit year) with /, ., - (with optional time)
    m_mdy = re.match(r'^([01]?\d)[-/\.]([0-3]?\d)[-/\.](\d{2,4})(?:\s+.*)?$', clean_text)
    if m_mdy:
        res = _valid_iso_date(int(m_mdy.group(3)), int(m_mdy.group(1)), int(m_mdy.group(2)))
        return res if res else fallback_date

    # 3. M/D without year with /, ., - (with optional time)
    m_md = re.match(r'^([01]?\d)[-/\.]([0-3]?\d)(?:\s+.*)?$', clean_text)
    if m_md:
        res = _valid_iso_date(default_year, int(m_md.group(1)), int(m_md.group(2)))
        return res if res else fallback_date

    # Textual month dictionary
    month_map = {
        "jan": 1, "january": 1,
        "feb": 2, "february": 2,
        "mar": 3, "march": 3,
        "apr": 4, "april": 4,
        "may": 5,
        "jun": 6, "june": 6,
        "jul": 7, "july": 7,
        "aug": 8, "august": 8,
        "sep": 9, "september": 9, "sept": 9,
        "oct": 10, "october": 10,
        "nov": 11, "november": 11,
        "dec": 12, "december": 12,
    }

    # 4a. Month Day, Year (e.g., Jun 15, 2026 or June 15 2026)
    m_txt1 = re.match(r'^([a-zA-Z]{3,9})\s+([0-3]?\d)(?:st|nd|rd|th)?,?\s+(\d{2,4})(?:\s+.*)?$', clean_text)
    if m_txt1:
        m_str, d, y = m_txt1.group(1).lower(), int(m_txt1.group(2)), int(m_txt1.group(3))
        if m_str in month_map:
            res = _valid_iso_date(y, month_map[m_str], d)
            return res if res else fallback_date

    # 4b. Day Month, Year (e.g., 15 Jun 2026 or 15 June 2026)
    m_txt2 = re.match(r'^([0-3]?\d)(?:st|nd|rd|th)?\s+([a-zA-Z]{3,9}),?\s+(\d{2,4})(?:\s+.*)?$', clean_text)
    if m_txt2:
        d, m_str, y = int(m_txt2.group(1)), m_txt2.group(2).lower(), int(m_txt2.group(3))
        if m_str in month_map:
            res = _valid_iso_date(y, month_map[m_str], d)
            return res if res else fallback_date

    # 4c. Month Day without year (e.g., Jun 15 or June 15)
    m_txt3 = re.match(r'^([a-zA-Z]{3,9})\s+([0-3]?\d)(?:st|nd|rd|th)?(?:\s+.*)?$', clean_text)
    if m_txt3:
        m_str, d = m_txt3.group(1).lower(), int(m_txt3.group(2))
        if m_str in month_map:
            res = _valid_iso_date(default_year, month_map[m_str], d)
            return res if res else fallback_date

    # 4d. Day Month without year (e.g., 15 Jun)
    m_txt4 = re.match(r'^([0-3]?\d)(?:st|nd|rd|th)?\s+([a-zA-Z]{3,9})(?:\s+.*)?$', clean_text)
    if m_txt4:
        d, m_str = int(m_txt4.group(1)), m_txt4.group(2).lower()
        if m_str in month_map:
            res = _valid_iso_date(default_year, month_map[m_str], d)
            return res if res else fallback_date

    return fallback_date


def extract_obj_id_from_url_or_style(href: str, style: str) -> Tuple[Optional[str], bool, str]:
    """
    Parses obj_id, video indicator, and resolved URL from fancybox href or tile style.
    Handles HTML entities (e.g., &amp; -> &, &quot; -> ") and video CSS background-image fallback (Rule 2.C).
    Case-insensitive when parsing CSS url(...) and iterates over all url(...) matches to find one with obj_attachment or obj=.

    Returns: (obj_id, is_video, resolved_url)
    """
    href_clean = html.unescape(href.strip()) if href else ""
    style_clean = html.unescape(style.strip()) if style else ""

    is_video = False
    resolved_url = href_clean

    # Rule 2.C: If href starts with '#' or lacks obj_attachment and obj=, it's a video post
    if href_clean.startswith("#") or not href_clean or ("obj_attachment" not in href_clean and "obj=" not in href_clean):
        is_video = True

    # Parse CSS background-image url(...) if needed or if style contains URL
    if is_video or "obj=" not in resolved_url:
        urls = []
        for match in re.finditer(r'url\(\s*[\'"]?([^\'"\)]+)[\'"]?\s*\)', style_clean, re.IGNORECASE):
            raw_u = match.group(1).strip()
            u = html.unescape(raw_u)
            urls.append(u)

        target_url = None
        for u in urls:
            if "obj_attachment" in u or "obj=" in u:
                target_url = u
                break
        if not target_url and urls:
            target_url = urls[0]

        if target_url:
            resolved_url = target_url

    # Extract obj ID parameter
    match_obj = re.search(r'obj=([^&#]+)', resolved_url)
    if match_obj:
        return match_obj.group(1), is_video, resolved_url

    return None, is_video, resolved_url


# -----------------------------------------------------------------------------
# Playwright DOM Interaction Functions
# -----------------------------------------------------------------------------

def parse_timeframe_links(page: Page) -> List[Dict[str, Any]]:
    """
    Finds and parses all timeframe month links in the Knockout.js timeline panel.

    Matches <li> elements whose inner text matches ^[a-z]{3}\\s+\\d{4}$ (Rule 2.A).
    Returns list of dicts: [{'text', 'year', 'month', 'locator', 'tile_locator'}, ...]
    """
    timeframe_items: List[Dict[str, Any]] = []
    months_map = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
                  "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}

    try:
        lis = page.locator("li").all()
        for li in lis:
            try:
                txt = li.inner_text().strip()
                if is_valid_timeframe_text(txt):
                    parts = txt.split()
                    month_name = parts[0].lower()
                    year_val = int(parts[1])
                    month_num = months_map.get(month_name, 1)

                    tile = li.locator("div.tile.pointable, div.tile").first
                    tile_loc = tile if tile.count() > 0 else li

                    timeframe_items.append({
                        "text": txt,
                        "year": year_val,
                        "month": month_num,
                        "locator": li,
                        "tile_locator": tile_loc
                    })
            except Exception:
                continue
    except Exception:
        pass

    return timeframe_items


def click_timeframe_tile(page: Page, tile_locator: Any) -> bool:
    """
    Clicks the timeframe month tile adhering to Rule 2.A.
    Target MUST be inner 'div.tile.pointable' element holding 'click: select' binding.

    Accepts either a Playwright Locator or a timeframe dict containing 'tile_locator'.
    """
    try:
        target = tile_locator
        if isinstance(tile_locator, dict):
            target = tile_locator.get("tile_locator") or tile_locator.get("locator")

        if hasattr(target, "click"):
            target.click()
            return True
        return False
    except Exception:
        return False


def extract_feed_items(page: Page, timeframe_year: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Extracts timeline feed items strictly scoped inside 'div.well.left-panel.pull-left' (Rule 2.B).
    Parses photo vs video background-image CSS and HTML unescaped URLs (Rule 2.C).

    Returns list of dictionaries representing parsed feed items.
    """
    items: List[Dict[str, Any]] = []

    # Rule 2.B: Scope search strictly inside left-panel timeline well
    timeline = page.locator("div.well.left-panel.pull-left")
    if timeline.count() == 0:
        # Strictly return empty list if timeline panel is missing to avoid querying top-bar child thumbnails
        return []

    feed_lis = timeline.locator("ul.thumbnails li").all()

    for li in feed_lis:
        try:
            fancybox = li.locator("a.fancybox").first
            if fancybox.count() == 0:
                continue

            raw_href = fancybox.get_attribute("href") or ""
            pointable_tile = li.locator("div.tile.pointable, div.tile").first
            style_attr = pointable_tile.get_attribute("style") or "" if pointable_tile.count() > 0 else ""

            obj_id, is_video, resolved_url = extract_obj_id_from_url_or_style(raw_href, style_attr)
            if not obj_id:
                continue

            # Overlay date parsing
            overlay_span = li.locator("span.name span").first
            raw_date = overlay_span.inner_text().strip() if overlay_span.count() > 0 else ""
            date_str = parse_date_overlay(raw_date, timeframe_year=timeframe_year)

            media_type = "video" if is_video else "photo"
            download_url = f"https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj={obj_id}&key={obj_id}"

            items.append({
                "obj_id": obj_id,
                "media_type": media_type,
                "is_video": is_video,
                "raw_href": raw_href,
                "resolved_url": resolved_url,
                "download_url": download_url,
                "date_str": date_str,
                "raw_date_text": raw_date,
                "locator": li
            })
        except Exception:
            continue

    return items


def dismiss_cdk_overlays(page: Page):
    """Dismisses open Angular CDK dropdown overlays cleanly."""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
    except Exception:
        pass


def discover_children_from_family_info(page: Page, context: BrowserContext, logger=None) -> List[Dict[str, str]]:
    """
    Discovers enrolled children and dependent_ids following Rule 5 (Angular CDK overlay parsing).

    Navigates to familyinfocenter.brighthorizons.com/home, clicks 'Actions' span triggers,
    clicks 'My Bright Day' menu item inside Angular CDK overlay container, and captures the
    new tab context to extract dependent_id from the URL.

    Returns list of child profiles: [{'name': 'Byron', 'given_name': 'Byron', 'full_name': '...', 'dependent_id': '...'}, ...]
    """
    log = logger or (lambda msg: None)
    children: List[Dict[str, str]] = []

    if "familyinfocenter.brighthorizons.com" not in page.url:
        page.goto("https://familyinfocenter.brighthorizons.com/home", wait_until="domcontentloaded")

    try:
        page.wait_for_selector("span:has-text('Actions')", timeout=15000)
    except Exception:
        pass

    page.wait_for_timeout(1000)
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

            if not card_name:
                continue

            full_name = card_name.strip()
            given_name = full_name.split()[0].capitalize()

            span.click()
            page.wait_for_timeout(800)

            mbd_item = page.locator("span.actions-menu-item-label", has_text="My Bright Day").first
            try:
                mbd_item.wait_for(state="visible", timeout=3000)
            except Exception:
                # Child has no active enrollment (Rule 5)
                log(f"Child '{given_name}' has no active My Bright Day enrollment. Skipping.")
                dismiss_cdk_overlays(page)
                continue

            with context.expect_page() as new_page_info:
                mbd_item.evaluate("(el) => (el.closest('a') || el.closest('button') || el).click()")

            new_page = new_page_info.value
            new_page.wait_for_load_state("domcontentloaded", timeout=10000)

            match = re.search(r'dependent_id=([^&]+)', new_page.url)
            if match:
                dep_id = match.group(1)
                children.append({
                    "name": given_name,
                    "given_name": given_name,
                    "full_name": full_name,
                    "dependent_id": dep_id
                })
                log(f"Discovered child: {given_name} (dependent_id: {dep_id})")

            new_page.close()
        except Exception as err:
            log(f"Error discovering child #{idx + 1}: {err}")
            dismiss_cdk_overlays(page)

    return children
