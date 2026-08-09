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

    Accepts a Playwright Locator, a timeframe dict containing 'tile_locator', or a string (e.g. 'jun 2026').
    """
    try:
        target = tile_locator
        if isinstance(tile_locator, str):
            return page.evaluate("""
                (text) => {
                    const parts = text.trim().toLowerCase().split(/\\s+/);
                    const mStr = parts[0] || '';
                    const yStr = parts[1] || '';
                    const lis = Array.from(document.querySelectorAll('li'));
                    const el = lis.find(item => {
                        const clean = (item.innerText || item.textContent || '').replace(/\\s+/g, ' ').trim().toLowerCase();
                        return mStr && yStr ? (clean.includes(mStr) && clean.includes(yStr)) : clean === text.trim().toLowerCase();
                    });
                    if (el) {
                        const tile = el.querySelector('div.tile') || el.querySelector('div') || el;
                        tile.scrollIntoView({ block: 'center', inline: 'center' });
                        if (window.jQuery) {
                            try { window.jQuery(tile).trigger('click'); } catch(e){}
                        }
                        const evt = new MouseEvent('click', { bubbles: true, cancelable: true, view: window });
                        tile.dispatchEvent(evt);
                        return true;
                    }
                    return false;
                }
            """, tile_locator)

        if isinstance(tile_locator, dict):
            target = tile_locator.get("tile_locator") or tile_locator.get("locator")

        if hasattr(target, "click"):
            try:
                target.click(force=True)
            except Exception:
                target.evaluate("(el) => el.click()")
            return True
        return False
    except Exception:
        return False


def check_month_busy_state(page: Page) -> bool:
    """
    Evaluates whether the timeframe month is currently in Busy State.
    
    Busy State is True IF AND ONLY IF:
    1) the div that has i.fa-spinner as an immediate child is NOT hidden
       AND
    2) the div that has h1.has-text('no events for the month') as an immediate child is hidden
    """
    return bool(page.evaluate("""
        () => {
            function isElementVisible(el) {
                if (!el) return false;
                return el.offsetParent !== null && 
                       window.getComputedStyle(el).display !== 'none' && 
                       window.getComputedStyle(el).visibility !== 'hidden';
            }

            // 1) The div that has i.fa-spinner as an immediate child is NOT hidden
            const spinner = document.querySelector('i.fa-spinner');
            let spinnerDivVisible = false;
            if (spinner && spinner.parentElement && spinner.parentElement.tagName.toLowerCase() === 'div') {
                spinnerDivVisible = isElementVisible(spinner.parentElement);
            }

            // 2) The div that has h1.has-text('no events for the month') as an immediate child is hidden
            let noEventsDivHidden = true;
            const h1s = Array.from(document.querySelectorAll('h1'));
            for (const h1 of h1s) {
                const txt = (h1.innerText || h1.textContent || '').toLowerCase();
                if (txt.includes('no events for the month')) {
                    if (h1.parentElement && h1.parentElement.tagName.toLowerCase() === 'div') {
                        if (isElementVisible(h1.parentElement)) {
                            noEventsDivHidden = false;
                            break;
                        }
                    }
                }
            }

            return spinnerDivVisible && noEventsDivHidden;
        }
    """))


def wait_for_month_feed_ready(page: Page, tf_text: str, max_wait_sec: float = 300.0, logger=None) -> bool:
    """
    Dynamically waits for Knockout.js feed items or 'no events for the month' indicator.
    
    Flow:
    1. Initial 2.5s buffer to let the page settle after tile click.
    2. Enters while loop checking Busy State until it becomes False or max_wait_sec is reached.
       If max_wait_sec is reached while still busy, raises TimeoutError.
    3. Exits loop and waits an additional 3.5s settling buffer to allow ul.thumbnails li or h1 elements to settle.
    4. Checks if the div that has h1 containing 'no events for the month' as immediate child is visible.
       - If visible -> returns False (month has no posts).
       - Else -> polls/verifies feed card readiness and returns True.
    """
    import time
    log_fn = logger if logger else print

    log_fn(f"Waiting for timeframe month '{tf_text}' (initial 2.5s buffer)...")
    page.wait_for_timeout(2500)  # Initial 2.5s settling buffer

    start_time = time.time()
    last_log_time = float('-inf')

    is_busy = True
    while time.time() - start_time < max_wait_sec:
        elapsed = time.time() - start_time

        if time.time() - last_log_time >= 6.0:
            log_fn(f"Waiting for Knockout feed '{tf_text}'... elapsed {elapsed:.1f}s (busy state active)")
            last_log_time = time.time()

        try:
            is_busy = check_month_busy_state(page)
            if not is_busy:
                break
        except Exception as e:
            log_fn(f"Error checking busy state for '{tf_text}': {e}")

        page.wait_for_timeout(350)

    if is_busy:
        err_msg = f"Max wait time ({max_wait_sec:.1f}s) reached waiting for timeframe month '{tf_text}' to finish busy state."
        log_fn(err_msg)
        raise TimeoutError(err_msg)

    # Post-busy settling buffer: 3.5s
    log_fn(f"Busy state cleared for '{tf_text}'. Waiting 3.5s settling buffer...")
    page.wait_for_timeout(3500)

    # Check if 'no events for the month' div is visible
    is_no_events_visible = bool(page.evaluate("""
        () => {
            function isElementVisible(el) {
                if (!el) return false;
                return el.offsetParent !== null && 
                       window.getComputedStyle(el).display !== 'none' && 
                       window.getComputedStyle(el).visibility !== 'hidden';
            }

            const h1s = Array.from(document.querySelectorAll('h1'));
            for (const h1 of h1s) {
                const txt = (h1.innerText || h1.textContent || '').toLowerCase();
                if (txt.includes('no events for the month')) {
                    if (h1.parentElement && h1.parentElement.tagName.toLowerCase() === 'div') {
                        if (isElementVisible(h1.parentElement)) {
                            return true;
                        }
                    }
                }
            }
            return false;
        }
    """))

    if is_no_events_visible:
        log_fn(f"Timeframe month '{tf_text}' confirmed empty ('no events for the month' div is visible).")
        return False

    # Otherwise, month has posts. Verify feed card readiness (ul.thumbnails li)
    log_fn(f"Timeframe month '{tf_text}' has posts. Verifying feed card readiness...")

    # Wait up to 10s for thumbnail card links to populate ready GCS / attachment URLs
    readiness_start = time.time()
    while time.time() - readiness_start < 10.0:
        status = page.evaluate("""
            () => {
                const timeline = document.querySelector('div.well.left-panel.pull-left, div.well.pull-left') || 
                                 Array.from(document.querySelectorAll('div.well')).find(el => !el.className.includes('pull-right')) || 
                                 document.body;

                const lis = Array.from(timeline.querySelectorAll('ul.thumbnails li')).filter(li => !li.querySelector('span[data-bind*="displayName"]'));

                let readyCount = 0;
                for (const li of lis) {
                    const fancybox = li.querySelector('a.fancybox');
                    const href = fancybox ? (fancybox.getAttribute('href') || '') : '';
                    if (href.startsWith('http') || href.includes('obj_attachment')) {
                        readyCount++;
                    } else if (href.startsWith('#')) {
                        const divId = href.replace(/^#/, '');
                        let relDiv = null;
                        try { relDiv = li.querySelector(`div#${CSS.escape(divId)}`); } catch(e){}
                        if (!relDiv) relDiv = document.getElementById(divId);
                        const relUrl = relDiv ? (relDiv.getAttribute('rel') || '') : '';
                        if (relUrl && (relUrl.includes('http') || relUrl.includes('obj'))) {
                            readyCount++;
                        }
                    }
                }
                return { totalCards: lis.length, readyCount };
            }
        """)

        p_count = status.get("totalCards", 0)
        ready_count = status.get("readyCount", 0)

        if p_count > 0 and (ready_count >= p_count or ready_count > 0):
            log_fn(f"Timeframe month '{tf_text}' feed is ready: Discovered {p_count} cards ({ready_count} matching media targets).")
            return True

        page.wait_for_timeout(500)

    log_fn(f"Timeframe month '{tf_text}' feed readiness check completed.")
    return True


def clean_full_res_url(url: str, obj_id: str, key_id: str) -> str:
    """
    Sanitizes primary download URLs to ensure they never request thumbnail assets.
    Strips 'thumbnail=true' / 'thumbnail=1' query parameters from portal endpoints,
    or falls back to the full-resolution portal endpoint for GCS thumbnail URLs.
    """
    fallback = f"https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj={obj_id}&key={key_id}"
    if not url:
        return fallback
    
    if "thumbnail=" in url.lower():
        if "obj_attachment" in url:
            cleaned = re.sub(r'[\?&]thumbnail=(true|false|1|0)', '', url, flags=re.IGNORECASE)
            return cleaned.replace("?&", "?").rstrip("?&")
        return fallback
    return url


def extract_feed_items(page: Page, timeframe_year: Optional[int] = None, logger: Optional[Callable[[str], None]] = None) -> List[Dict[str, Any]]:
    """
    Parses media posts (photos and videos) from the active Knockout.js timeline.
    Uses 1-batch JS evaluation fast-path with fallback to CDP locator iteration.
    """
    import re
    items: List[Dict[str, Any]] = []

    # Fast-Path: Perform 1 single in-browser JS evaluation to fetch all card attributes at once (3ms)
    raw_cards = None
    try:
        raw_cards = page.evaluate("""
            () => {
                const timeline = document.querySelector('div.well.left-panel.pull-left') || document.querySelector('div.well.pull-left') || document.querySelector('div.well') || document.body;
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
                raw_url = resolved_url
            elif resolved_url.startswith("/"):
                raw_url = f"https://mybrightday.brighthorizons.com{resolved_url}"
            else:
                raw_url = f"https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj={obj_id}&key={key_id}"

            download_url = clean_full_res_url(raw_url, obj_id, key_id)

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
    Discovers enrolled children and dependent_ids following exact DOM structure:
    - Child cards are <app-child> elements.
    - Child full name is in div.card-title h1 inside the app-child card.
    - Actions trigger inside app-child is clicked to open the Angular CDK overlay dropdown.
    - "My Bright Day" menu item opens new tab with dependent_id in the URL.
    - Zero fallback names, zero hardcoded children.
    """
    log = logger or (lambda msg: None)
    children: List[Dict[str, str]] = []

    if "familyinfocenter.brighthorizons.com" not in page.url:
        page.goto("https://familyinfocenter.brighthorizons.com/home", wait_until="domcontentloaded")

    try:
        page.wait_for_selector("app-child", timeout=15000)
    except Exception:
        pass

    page.wait_for_timeout(1000)
    cards = page.locator("app-child").all()
    log(f"Found {len(cards)} child card(s) (<app-child>) on portal home.")

    for idx, card in enumerate(cards):
        try:
            title_el = card.locator("div.card-title h1").first
            try:
                title_el.wait_for(state="visible", timeout=3000)
            except Exception:
                log(f"Child card #{idx + 1} div.card-title h1 not visible. Skipping.")
                continue

            full_name = title_el.inner_text().strip()
            if not full_name:
                log(f"Child card #{idx + 1} div.card-title h1 has empty text. Skipping.")
                continue

            given_name = full_name.split()[0].capitalize()
            log(f"Inspecting child card #{idx + 1} of {len(cards)}: '{full_name}' (Given: '{given_name}')...")

            actions_trigger = card.locator("a.mat-mdc-menu-trigger, a:has-text('Actions'), span:has-text('Actions'), button:has-text('Actions')").first
            if not actions_trigger:
                log(f"Child card '{given_name}' has no Actions trigger. Skipping.")
                continue

            actions_trigger.click()
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
                child_profile = {
                    "name": given_name,
                    "given_name": given_name,
                    "full_name": full_name,
                    "dependent_id": dep_id
                }
                if not any(c["dependent_id"] == dep_id for c in children):
                    children.append(child_profile)
                    log(f"Discovered active child #{len(children)}: {given_name} (dependent_id: {dep_id[:8]}...)")

            try:
                new_page.close()
            except Exception:
                pass

            dismiss_cdk_overlays(page)
        except Exception as err:
            log(f"Error discovering child card #{idx + 1}: {err}")
            dismiss_cdk_overlays(page)

    log(f"Child discovery complete. Total active child profiles found: {len(children)}")
    return children
