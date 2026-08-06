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
from typing import List, Dict, Any, Optional, Tuple, Callable
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


def extract_obj_id_from_url_or_style(href: str = "", style: str = "", rel: str = "") -> Tuple[Optional[str], bool, str]:
    """
    Extracts attachment obj_id, is_video boolean flag, and resolved_url from post elements.
    Handles direct Google Cloud Storage signed URLs (https://storage.googleapis.com/mbd-attachments-prod/<obj_id>/...)
    as well as legacy /remote/v1/obj_attachment endpoints and style background-image properties.
    
    Returns: (obj_id, is_video, resolved_url)
    """
    href_clean = html.unescape(href.strip()) if href else ""
    style_clean = html.unescape(style.strip()) if style else ""
    rel_clean = html.unescape(rel.strip()) if rel else ""

    is_video = href_clean.startswith("#") or bool(re.search(r'\.(mp4|mov|webm)\b', rel_clean, re.I)) or "video" in rel_clean.lower() or "video" in href_clean.lower()

    # 1. Check direct GCS signed URL in rel (for video elements <div id="..." rel="https://storage.googleapis.com/...">)
    m_gcs_rel = re.search(r'/mbd-attachments-prod/([a-f0-9]{12,64})/', rel_clean)
    if m_gcs_rel:
        return m_gcs_rel.group(1), True, rel_clean

    # 2. Check direct GCS signed URL in href (for photo elements <a href="https://storage.googleapis.com/...">)
    m_gcs_href = re.search(r'/mbd-attachments-prod/([a-f0-9]{12,64})/', href_clean)
    if m_gcs_href:
        return m_gcs_href.group(1), is_video, href_clean

    # 3. Check direct GCS signed URL in style background-image
    for match in re.finditer(r'url\(\s*[\'"]?([^\'"\)]+)[\'"]?\s*\)', style_clean, re.IGNORECASE):
        u = html.unescape(match.group(1).strip())
        m_gcs_style = re.search(r'/mbd-attachments-prod/([a-f0-9]{12,64})/', u)
        if m_gcs_style:
            return m_gcs_style.group(1), is_video, u

    # 4. Check legacy obj_attachment URL params in href, rel, or style
    for candidate in [href_clean, rel_clean, style_clean]:
        if candidate and not candidate.startswith("#"):
            m_obj = re.search(r'obj=([^&#"\'\)\s]+)', candidate)
            if m_obj:
                return m_obj.group(1), is_video, candidate

    # 5. Fallback: video fragment anchor (#6986168d2bb117b0dc910b3b-default)
    if href_clean.startswith("#"):
        frag = href_clean.lstrip("#")
        m_frag = re.search(r'([a-f0-9]{12,64})', frag, re.IGNORECASE)
        if m_frag:
            video_obj_id = m_frag.group(1)
            video_url = rel_clean if rel_clean.startswith("http") else f"https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj={video_obj_id}&key={video_obj_id}"
            return video_obj_id, True, video_url

    resolved_url = rel_clean or href_clean
    m_res = re.search(r'obj=([^&#"\'\)\s]+)', resolved_url)
    if m_res:
        return m_res.group(1), is_video, resolved_url

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


def wait_for_month_feed_ready(page: Page, tf_text: str, max_wait_sec: float = 300.0, max_retries: int = 2, logger=None) -> bool:
    """
    Dynamically waits up to max_wait_sec for Knockout.js feed items or 'no events for the month' indicator.
    Supports re-clicking the month tile up to max_retries times if loading stalls.
    
    Returns True if month has events and media URLs are fully populated.
    Returns False if confirmed empty or timed out.
    """
    import time
    log_fn = logger if logger else print

    for attempt in range(max_retries + 1):
        if attempt > 0:
            log_fn(f"[Retry #{attempt}/{max_retries}] Re-clicking timeframe month tile '{tf_text}'...")
            try:
                clicked = page.evaluate("""
                    (text) => {
                        const targetText = text.replace(/\\s+/g, ' ').trim().toLowerCase();
                        const el = Array.from(document.querySelectorAll('li')).find(item => {
                            const cleanItemText = (item.innerText || item.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                            return cleanItemText === targetText;
                        });
                        if (el) {
                            const clickable = el.querySelector('div.tile') || el.querySelector('div') || el;
                            clickable.click();
                            return true;
                        }
                        return false;
                    }
                """, tf_text)
            except Exception as e:
                log_fn(f"Re-click tile exception: {e}")

        start_time = time.time()
        while time.time() - start_time < (max_wait_sec / (max_retries + 1)):
            try:
                empty_loc = page.locator("div:has(> h1:has-text('no events for the month'))").first
                timeline = page.locator("div.well.left-panel.pull-left")
                posts_loc = timeline.locator("ul.thumbnails li") if timeline.count() > 0 else page.locator("div.well.left-panel.pull-left ul.thumbnails li")
                
                # Check for empty month header
                if empty_loc.count() > 0 and empty_loc.is_visible():
                    # Wait 2.5s false-positive safety buffer to verify no post items arrive
                    page.wait_for_timeout(2500)
                    if posts_loc.count() == 0:
                        log_fn(f"Timeframe month '{tf_text}' confirmed empty ('no events for the month').")
                        return False
                
                # Check for feed items
                p_count = posts_loc.count()
                if p_count > 0:
                    # Verify DOM readiness: ensure all items have populated URLs
                    ready_count = 0
                    lis = posts_loc.all()
                    for li in lis:
                        fancybox = li.locator("a.fancybox").first
                        if fancybox.count() > 0:
                            href = fancybox.get_attribute("href") or ""
                            if href.startswith("http") or href.startswith("https://storage.googleapis.com") or "obj_attachment" in href:
                                ready_count += 1
                            elif href.startswith("#"):
                                div_id = href.lstrip("#")
                                rel_div = li.locator(f"div#{div_id}").first
                                rel_url = rel_div.get_attribute("rel") if rel_div.count() > 0 else ""
                                if rel_url and ("http" in rel_url or "storage.googleapis.com" in rel_url or "obj" in rel_url):
                                    ready_count += 1
                    
                    if ready_count >= p_count or (p_count > 0 and ready_count > 0 and (time.time() - start_time > 5.0)):
                        log_fn(f"Timeframe month '{tf_text}' feed is ready: Discovered {p_count} total <li> cards ({ready_count} matching direct GCS signed URL targets).")
                        return True
            except Exception:
                pass
            
            page.wait_for_timeout(250)

    log_fn(f"Timed out waiting for timeframe month '{tf_text}' after {max_retries + 1} attempts.")
    return False


def extract_feed_items(page: Page, timeframe_year: Optional[int] = None, logger: Optional[Callable[[str], None]] = None) -> List[Dict[str, Any]]:
    """
    Extracts timeline feed items strictly scoped inside 'div.well.left-panel.pull-left' (Rule 2.B).
    Parses direct GCS signed URLs, photo vs video background-image CSS, and overlay dates.

    Returns list of dictionaries representing parsed feed items.
    """
    if logger:
        logger(f"Starting DOM feed item extraction for timeframe year {timeframe_year}...")

    items: List[Dict[str, Any]] = []

    # Fast-Path: Perform 1 single in-browser JS evaluation to fetch all card attributes at once (3ms)
    raw_cards = None
    try:
        raw_cards = page.evaluate("""
            () => {
                const timeline = document.querySelector('div.well.left-panel.pull-left');
                if (!timeline) return null;
                const lis = Array.from(timeline.querySelectorAll('ul.thumbnails li'));
                return lis.map(li => {
                    const fancybox = li.querySelector('a.fancybox');
                    const href = fancybox ? (fancybox.getAttribute('href') || '') : '';
                    const tile = li.querySelector('div.tile.pointable, div.tile');
                    const style = tile ? (tile.getAttribute('style') || '') : '';
                    
                    let rel = '';
                    if (href.startsWith('#')) {
                        const divId = href.replace(/^#/, '');
                        let vidDiv = null;
                        try {
                            vidDiv = li.querySelector(`div#${CSS.escape(divId)}`);
                        } catch(e) {}
                        if (!vidDiv) vidDiv = document.getElementById(divId);
                        if (vidDiv) rel = vidDiv.getAttribute('rel') || '';
                    }
                    
                    const span = li.querySelector('span.name span');
                    const rawDateText = span ? (span.innerText || span.textContent || '').trim() : '';
                    
                    const footer = li.querySelector('.footer.note');
                    const commentText = footer ? (footer.innerText || footer.textContent || '').trim() : '';
                    
                    return {
                        href: href,
                        style: style,
                        rel: rel,
                        rawDateText: rawDateText,
                        commentText: commentText,
                        hasFancybox: !!fancybox
                    };
                });
            }
        """)
    except Exception as eval_err:
        if logger:
            logger(f"Fast-path JS evaluation notice: {eval_err}. Falling back to CDP locator iteration...")

    if isinstance(raw_cards, list):
        total_lis = len(raw_cards)
        if logger:
            logger(f"Fast-path DOM parser: Retrieved {total_lis} raw feed cards in 1 batch JS call. Processing metadata...")

        for idx, card in enumerate(raw_cards):
            if not card.get("hasFancybox") and not card.get("href"):
                continue

            raw_href = card.get("href") or ""
            style_attr = card.get("style") or ""
            rel_attr = card.get("rel") or ""

            obj_id, is_video, resolved_url = extract_obj_id_from_url_or_style(raw_href, style_attr, rel_attr)
            if not obj_id:
                continue

            m_key = re.search(r'key=([^&#"\'\)\s]+)', resolved_url) or re.search(r'key=([^&#"\'\)\s]+)', raw_href) or re.search(r'key=([^&#"\'\)\s]+)', rel_attr) or re.search(r'key=([^&#"\'\)\s]+)', style_attr)
            key_id = m_key.group(1) if m_key else obj_id

            raw_date = card.get("rawDateText") or ""
            date_str = parse_date_overlay(raw_date, timeframe_year=timeframe_year)
            comment_text = card.get("commentText") or ""

            media_type = "video" if is_video else "photo"
            if resolved_url.startswith("http"):
                download_url = resolved_url
            elif resolved_url.startswith("/"):
                download_url = f"https://mybrightday.brighthorizons.com{resolved_url}"
            else:
                download_url = f"https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj={obj_id}&key={key_id}"

            items.append({
                "obj_id": obj_id,
                "key_id": key_id,
                "media_type": media_type,
                "is_video": is_video,
                "raw_href": raw_href,
                "resolved_url": resolved_url,
                "download_url": download_url,
                "date_str": date_str,
                "raw_date_text": raw_date,
                "comment_text": comment_text,
            })

            if logger and (idx + 1) % 50 == 0:
                logger(f"Parsing batch progress: processed {idx + 1}/{total_lis} DOM feed cards...")

        if logger:
            logger(f"DOM feed extraction finished: Discovered {total_lis} total <li> cards, extracted {len(items)} valid media items with direct GCS signed URL targets.")

        return items

    # Fallback Path: Locator-based iteration (for unit tests / mock objects)
    timeline = page.locator("div.well.left-panel.pull-left")
    if timeline.count() == 0:
        if logger:
            logger("Feed Item Parser: No timeline well 'div.well.left-panel.pull-left' found on page.")
        return []

    feed_lis = timeline.locator("ul.thumbnails li").all()
    total_lis = len(feed_lis)
    if logger:
        logger(f"CDP Locator parser: Found {total_lis} total <li> cards in timeline well. Parsing element by element...")

    for idx, li in enumerate(feed_lis):
        try:
            fancybox = li.locator("a.fancybox").first
            if fancybox.count() == 0:
                continue

            raw_href = fancybox.get_attribute("href") or ""
            pointable_tile = li.locator("div.tile.pointable, div.tile").first
            style_attr = pointable_tile.get_attribute("style") or "" if pointable_tile.count() > 0 else ""

            rel_attr = ""
            if raw_href.startswith("#"):
                div_id = raw_href.lstrip("#")
                try:
                    vid_div = li.locator(f"div#{div_id}").first
                    if vid_div.count() > 0:
                        rel_attr = vid_div.get_attribute("rel") or ""
                except Exception:
                    pass

            obj_id, is_video, resolved_url = extract_obj_id_from_url_or_style(raw_href, style_attr, rel_attr)
            if not obj_id:
                continue

            raw_date = ""
            try:
                overlay_span = li.locator("span.name span").first
                raw_date = (overlay_span.inner_text() or "").strip()
            except Exception:
                pass
            date_str = parse_date_overlay(raw_date, timeframe_year=timeframe_year)

            comment_text = ""
            try:
                footer_note = li.locator(".footer.note").first
                comment_text = (footer_note.inner_text() or "").strip()
            except Exception:
                pass

            m_key = re.search(r'key=([^&#"\'\)\s]+)', resolved_url) or re.search(r'key=([^&#"\'\)\s]+)', raw_href) or re.search(r'key=([^&#"\'\)\s]+)', rel_attr) or re.search(r'key=([^&#"\'\)\s]+)', style_attr)
            key_id = m_key.group(1) if m_key else obj_id

            media_type = "video" if is_video else "photo"
            if resolved_url.startswith("http"):
                download_url = resolved_url
            elif resolved_url.startswith("/"):
                download_url = f"https://mybrightday.brighthorizons.com{resolved_url}"
            else:
                download_url = f"https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj={obj_id}&key={key_id}"

            items.append({
                "obj_id": obj_id,
                "key_id": key_id,
                "media_type": media_type,
                "is_video": is_video,
                "raw_href": raw_href,
                "resolved_url": resolved_url,
                "download_url": download_url,
                "date_str": date_str,
                "raw_date_text": raw_date,
                "comment_text": comment_text,
                "locator": li
            })

            if logger and (idx + 1) % 25 == 0:
                logger(f"Parsing batch progress: processed {idx + 1}/{total_lis} DOM feed cards...")
        except Exception:
            continue

    if logger:
        logger(f"DOM feed extraction finished: Discovered {total_lis} total <li> cards, extracted {len(items)} valid media items with direct GCS signed URL targets.")

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
