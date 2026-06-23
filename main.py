# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Marco Massarelli

# /// script
# requires-python = ">=3.9"
# dependencies = [
#     "playwright",
#     "piexif",
# ]
# ///

import json
import os
import re
import sys
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse, parse_qs
from playwright.sync_api import sync_playwright

try:
    from organize_folders import flatten_folders, nest_folders
except ImportError:
    def flatten_folders(downloads_dir):
        pass
    def nest_folders(downloads_dir):
        pass

def load_config():
    """Loads configuration from config.json."""
    if not os.path.exists('config.json'):
        print("Error: config.json file not found!")
        sys.exit(1)
    with open('config.json', 'r') as f:
        return json.load(f)

def load_manifest(downloads_dir):
    """Loads the downloaded photos manifest to avoid duplicate downloads."""
    manifest_path = os.path.join(downloads_dir, 'manifest.json')
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not parse manifest.json: {e}. Starting fresh.")
            return {}
    return {}

def save_manifest(downloads_dir, manifest):
    """Saves the download manifest."""
    os.makedirs(downloads_dir, exist_ok=True)
    manifest_path = os.path.join(downloads_dir, 'manifest.json')
    try:
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)
    except Exception as e:
        print(f"Error saving manifest: {e}")

def parse_timeframe_context(tf_text):
    """Parses month and year from timeframe string like 'jun 2026'."""
    if not tf_text:
        return None, None
    months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    m = re.match(r'^([a-z]{3})\s+(\d{4})$', tf_text.lower().strip())
    if m:
        month_str, year_str = m.groups()
        if month_str in months:
            month_idx = months.index(month_str) + 1
            return int(year_str), month_idx
    return None, None

def parse_date_from_overlay(date_text, timeframe_year=None):
    """Parses date from overlay text (e.g. '6/22' or '06/22/2026')."""
    if not date_text:
        return None
    
    text = date_text.strip()
    
    # 1. Matches M/D or MM/DD (e.g. '6/22')
    m = re.match(r'^(\d{1,2})/(\d{1,2})$', text)
    if m:
        month_val, day_val = m.groups()
        year = timeframe_year if timeframe_year else datetime.now().year
        return f"{year:04d}-{int(month_val):02d}-{int(day_val):02d}"
        
    # 2. Matches M/D/YY or MM/DD/YYYY (e.g. '6/22/26' or '6/22/2026')
    m = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2,4})$', text)
    if m:
        month_val, day_val, y_val = m.groups()
        year = int(y_val)
        if year < 100:
            year += 2000
        return f"{year:04d}-{int(month_val):02d}-{int(day_val):02d}"
        
    return None

def parse_date_from_text(text, timeframe_year=None, timeframe_month=None, current_date=None):
    """
    Parses a date from comment/footer text.
    Handles 'Today', 'Yesterday', 'Month DD, YYYY', 'Month DD', 'MM/DD/YYYY', 'DD/MM/YYYY'.
    Uses timeframe context to resolve ambiguous dates (missing year).
    """
    if not text:
        return None
    if not current_date:
        current_date = datetime.now()
        
    text_lower = text.lower().strip()
    
    # 1. Relative Dates
    if 'today' in text_lower:
        if timeframe_year and timeframe_month:
            if current_date.year == timeframe_year and current_date.month == timeframe_month:
                return current_date.strftime('%Y-%m-%d')
            else:
                return f"{timeframe_year:04d}-{timeframe_month:02d}-{current_date.day:02d}"
        return current_date.strftime('%Y-%m-%d')
        
    if 'yesterday' in text_lower:
        yesterday = current_date - timedelta(days=1)
        if timeframe_year and timeframe_month:
            if yesterday.year == timeframe_year and yesterday.month == timeframe_month:
                return yesterday.strftime('%Y-%m-%d')
            else:
                return f"{timeframe_year:04d}-{timeframe_month:02d}-{yesterday.day:02d}"
        return yesterday.strftime('%Y-%m-%d')
        
    months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    month_pattern = r'\b(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec)\b'
    
    # 2. Month Day, Year (e.g. "June 22, 2026", "Jun 22, 2026")
    m = re.search(month_pattern + r'\s+(\d{1,2})(?:st|nd|rd|th)?\s*,\s*(\d{4})', text_lower)
    if m:
        month_str, day_str, year_str = m.groups()
        month_idx = next(i for i, val in enumerate(months) if month_str.startswith(val)) + 1
        return f"{int(year_str):04d}-{month_idx:02d}-{int(day_str):02d}"
        
    # Month Day Year (no comma, e.g. "June 22 2026")
    m = re.search(month_pattern + r'\s+(\d{1,2})(?:st|nd|rd|th)?\s+(\d{4})', text_lower)
    if m:
        month_str, day_str, year_str = m.groups()
        month_idx = next(i for i, val in enumerate(months) if month_str.startswith(val)) + 1
        return f"{int(year_str):04d}-{month_idx:02d}-{int(day_str):02d}"

    # Day Month Year (e.g. "22 June 2026")
    m = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+' + month_pattern + r'\s+(\d{4})\b', text_lower)
    if m:
        day_str, month_str, year_str = m.groups()
        month_idx = next(i for i, val in enumerate(months) if month_str.startswith(val)) + 1
        return f"{int(year_str):04d}-{month_idx:02d}-{int(day_str):02d}"

    # Month Day (no year, e.g. "June 22") - use timeframe year, fallback to current year
    m = re.search(month_pattern + r'\s+(\d{1,2})(?:st|nd|rd|th)?\b', text_lower)
    if m:
        month_str, day_str = m.groups()
        month_idx = next(i for i, val in enumerate(months) if month_str.startswith(val)) + 1
        year = timeframe_year if timeframe_year else current_date.year
        return f"{year:04d}-{month_idx:02d}-{int(day_str):02d}"

    # Day Month (no year, e.g. "22 June") - use timeframe year, fallback to current year
    m = re.search(r'\b(\d{1,2})(?:st|nd|rd|th)?\s+' + month_pattern + r'\b', text_lower)
    if m:
        day_str, month_str = m.groups()
        month_idx = next(i for i, val in enumerate(months) if month_str.startswith(val)) + 1
        year = timeframe_year if timeframe_year else current_date.year
        return f"{year:04d}-{month_idx:02d}-{int(day_str):02d}"

    # 3. Numeric dates
    # YYYY-MM-DD
    m = re.search(r'\b(\d{4})[-/](\d{1,2})[-/](\d{1,2})\b', text)
    if m:
        y, m_val, d = m.groups()
        return f"{int(y):04d}-{int(m_val):02d}-{int(d):02d}"
        
    # MM/DD/YYYY or DD/MM/YYYY
    m = re.search(r'\b(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})\b', text)
    if m:
        val1, val2, y_val = m.groups()
        year = int(y_val)
        if year < 100:
            year += 2000
        
        if int(val1) > 12: # DD/MM/YYYY
            return f"{year:04d}-{int(val2):02d}-{int(val1):02d}"
        else: # MM/DD/YYYY
            return f"{year:04d}-{int(val1):02d}-{int(val2):02d}"
            
    return None

def detect_extension(body, content_type=''):
    """Detects file extension using file magic bytes, with content-type fallback."""
    if not body:
        return ".jpg"
        
    # Check Magic Bytes
    if body.startswith(b'\x89PNG\r\n\x1a\n'):
        return ".png"
    if body.startswith(b'\xff\xd8\xff'):
        return ".jpg"
    if body.startswith(b'RIFF') and body[8:12] == b'WEBP':
        return ".webp"
    if body.startswith(b'GIF87a') or body.startswith(b'GIF89a'):
        return ".gif"
        
    # Video Check (MP4/MOV container signatures)
    if b'ftypmp4' in body[:30] or b'ftypisom' in body[:30] or (len(body) > 8 and body[4:8] == b'ftyp'):
        if b'qt  ' in body[:30]:
            return ".mov"
        return ".mp4"
        
    # Fallback to headers
    ct = content_type.lower()
    if 'png' in ct:
        return ".png"
    elif 'heic' in ct:
        return ".heic"
    elif 'gif' in ct:
        return ".gif"
    elif 'mp4' in ct:
        return ".mp4"
    elif 'quicktime' in ct or 'mov' in ct:
        return ".mov"
    elif 'video/webm' in ct or 'webm' in ct:
        return ".webm"
    elif 'video/' in ct:
        return ".mp4"
        
    return ".jpg"

def write_exif_comment(filepath, comment):
    """Writes the overlay comment text to the image's EXIF UserComment & ImageDescription tags."""
    if not comment:
        return False
    try:
        import piexif
        # Load existing exif or initialize clean dict
        try:
            exif_dict = piexif.load(filepath)
        except Exception:
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}
            
        # Write ImageDescription (0th IFD) - ASCII type
        exif_dict["0th"][piexif.ImageIFD.ImageDescription] = comment.encode('utf-8')
        
        # Write UserComment (Exif IFD) - UNDEFINED type (requires 8-byte ASCII format header prefix)
        exif_dict["Exif"][piexif.ExifIFD.UserComment] = b'ASCII\x00\x00\x00' + comment.encode('utf-8')
        
        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, filepath)
        return True
    except Exception as e:
        print(f"         Warning: Could not write EXIF comment to {os.path.basename(filepath)}: {e}")
        return False

def write_png_comment(filepath, comment):
    """Writes the overlay comment text to the PNG's tEXt Description chunk."""
    if not comment:
        return False
    try:
        import zlib
        import struct
        with open(filepath, 'rb') as f:
            data = f.read()
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            return False
            
        keyword = 'Description'
        search_keyword = b'tEXt' + keyword.encode('latin-1', 'ignore') + b'\x00'
        if search_keyword in data:
            return False # already written
            
        chunk_type = b'tEXt'
        chunk_data = keyword.encode('latin-1', 'ignore') + b'\x00' + comment.encode('latin-1', 'ignore')
        chunk_len = len(chunk_data)
        chunk_len_bytes = struct.pack('>I', chunk_len)
        crc = zlib.crc32(chunk_type + chunk_data) & 0xffffffff
        crc_bytes = struct.pack('>I', crc)
        new_chunk = chunk_len_bytes + chunk_type + chunk_data + crc_bytes
        
        if data[12:16] == b'IHDR':
            ihdr_end = 33
            new_data = data[:ihdr_end] + new_chunk + data[ihdr_end:]
            with open(filepath, 'wb') as f:
                f.write(new_data)
            return True
    except Exception as e:
        print(f"         Warning: Could not write PNG comment to {os.path.basename(filepath)}: {e}")
        return False
    return False

def run_verification(downloads_dir, is_flat=True):
    """Verifies that all files listed in manifest exist on disk, corrects timestamps, and updates comments."""
    manifest_path = os.path.join(downloads_dir, 'manifest.json')
    if not os.path.exists(manifest_path):
        print(f"Error: {manifest_path} not found!")
        return
        
    try:
        with open(manifest_path, 'r') as f:
            manifest = json.load(f)
    except Exception as e:
        print(f"Error reading manifest: {e}")
        return
        
    print(f"Loaded {len(manifest)} items from manifest.")
    print("Starting verification and metadata injection...\n")
    
    total_items = len(manifest)
    verified_files = 0
    missing_files = 0
    png_updated = 0
    jpeg_updated = 0
    timestamps_corrected = 0
    
    for obj_id, item in manifest.items():
        child = item.get('child')
        year = item.get('year')
        month = item.get('month')
        filename = item.get('filename')
        date_str = item.get('date')
        comment = item.get('comment', '')
        
        if not all([child, year, month, filename]):
            print(f"Skipping malformed manifest entry: {obj_id}")
            continue
            
        if is_flat:
            filepath = os.path.join(downloads_dir, child, filename)
        else:
            filepath = os.path.join(downloads_dir, child, year, month, filename)
        
        # 1. Verify existence on file system
        if not os.path.exists(filepath):
            print(f"[MISSING] File does not exist: {filepath}")
            missing_files += 1
            continue
            
        verified_files += 1
        
        # 2. Inject comment metadata
        ext = os.path.splitext(filename)[1].lower()
        if comment:
            if ext in ['.jpg', '.jpeg']:
                if write_exif_comment(filepath, comment):
                    jpeg_updated += 1
            elif ext == '.png':
                if write_png_comment(filepath, comment):
                    png_updated += 1
                    
        # 3. Check and correct file modification timestamp (10:00 AM New York time)
        if date_str:
            try:
                from zoneinfo import ZoneInfo
                expected_dt = datetime.strptime(f"{date_str} 10:00:00", "%Y-%m-%d %H:%M:%S")
                expected_dt = expected_dt.replace(tzinfo=ZoneInfo("America/New_York"))
                expected_timestamp = expected_dt.timestamp()
                
                # Check current modification time
                current_timestamp = os.path.getmtime(filepath)
                # Allow minor float discrepancies (within 2 seconds)
                if abs(current_timestamp - expected_timestamp) > 2:
                    os.utime(filepath, (expected_timestamp, expected_timestamp))
                    timestamps_corrected += 1
            except Exception as e:
                print(f"  Warning: Could not set timestamp for {filename}: {e}")
                
    print("\n" + "="*50)
    print("VERIFICATION AND METADATA INJECTION SUMMARY")
    print("="*50)
    print(f"Total manifest entries:   {total_items}")
    print(f"Files verified on disk:   {verified_files}")
    print(f"Files missing from disk:  {missing_files}")
    print(f"PNG comments embedded:    {png_updated}")
    print(f"JPEG comments embedded:   {jpeg_updated}")
    print(f"Timestamps corrected:     {timestamps_corrected}")
    print("="*50)

def safe_goto(page, url, retries=3, timeout=30000):
    """Safely navigates to a URL with error retries."""
    for attempt in range(1, retries + 1):
        try:
            print(f"   Navigating to {url} (Attempt {attempt}/{retries})...")
            page.goto(url, timeout=timeout, wait_until="load")
            return True
        except Exception as e:
            print(f"   Warning: Navigation attempt {attempt} failed: {e}")
            if attempt < retries:
                page.wait_for_timeout(3000 * attempt) # Exponential backoff
    return False

def scroll_to_bottom(page):
    """Scrolls down the page until no new content is loaded to ensure all photos are rendered."""
    last_height = page.evaluate("document.body.scrollHeight")
    no_change_count = 0
    max_scrolls = 50  # Cap scrolling to prevent infinite loops on page issues
    scrolls = 0
    
    while scrolls < max_scrolls:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(2500) # wait for new items to lazy-load
        
        new_height = page.evaluate("document.body.scrollHeight")
        scrolls += 1
        if new_height == last_height:
            # Scroll up slightly and scroll down again to shake loose lazy loaders
            page.evaluate("window.scrollTo(0, document.body.scrollHeight - 600)")
            page.wait_for_timeout(500)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2000)
            
            new_height = page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                no_change_count += 1
                if no_change_count >= 2:
                    break
            else:
                no_change_count = 0
        else:
            no_change_count = 0
            
        last_height = new_height
        print(f"      Scroll position: {last_height}px")

def discover_children(page, context):
    """
    Auto-detects children (name + dependent_id) from the Bright Horizons portal.

    Strategy 1: Navigate to familyinfocenter.brighthorizons.com/home and scrape
                the "My Bright Day" action links. These are plain <a href> links
                containing ?dependent_id=<ID>, with the child name in the
                surrounding card heading.
    Strategy 2: Fallback — network interception on the mybrightday SPA dashboard.

    Returns a list of dicts: [{"name": str, "dependent_id": str}, ...]
    """
    print("   Auto-detecting children from Bright Horizons family portal...")
    
    # --- Strategy 1: familyinfocenter — click each "Actions" span (Angular component),
    # then read the "My Bright Day" href which contains the dependent_id.
    # The dropdown is dynamically rendered so links are not in the DOM until opened.
    # Children without an active enrollment (e.g. Elizabeth) won't have a My Bright Day
    # link in their dropdown, so they are naturally skipped.
    print("   Navigating to family info center home...")
    page.goto("https://familyinfocenter.brighthorizons.com/home")
    page.wait_for_timeout(5000)

    children = []
    seen_ids = set()

    # The "Actions" trigger is a <span> inside an Angular component (not a <button>)
    actions_buttons = page.locator("span", has_text="Actions").all()
    print(f"   Found {len(actions_buttons)} child card(s) with Actions menu.")

    for btn in actions_buttons:
        try:
            # Get the child name from the H1 heading in the card (before opening dropdown)
            card_name = btn.evaluate("""
                (el) => {
                    let node = el.parentElement;
                    while (node && node !== document.body) {
                        const h = node.querySelector('h1, h2, h3, h4, h5, h6');
                        if (h) return (h.innerText || h.textContent || '').trim();
                        node = node.parentElement;
                    }
                    return '';
                }
            """)

            # Click the Actions span to open the dropdown
            btn.click()
            page.wait_for_timeout(1500)

            # The dropdown items are <span class="actions-menu-item-label"> inside a
            # CDK overlay. We must target that class specifically — the generic
            # "text=My Bright Day" locator matches the promotional h4 banner instead.
            mbd = page.locator("span.actions-menu-item-label", has_text="My Bright Day").first
            try:
                mbd.wait_for(state="visible", timeout=3000)
            except Exception:
                # No "My Bright Day" option in this dropdown — child not enrolled, skip
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
                continue

            # Clicking the span's parent (the actual <a> or <button>) opens a new tab
            # with the dependent_id in the URL. Capture that tab.
            with context.expect_page() as new_page_info:
                mbd.evaluate("(el) => (el.closest('a') || el.closest('button') || el).click()")

            new_page = new_page_info.value
            new_page.wait_for_load_state("domcontentloaded", timeout=10000)
            new_url = new_page.url
            new_page.close()

            m = re.search(r'dependent_id=([^&]+)', new_url)
            if not m:
                continue

            dep_id = m.group(1)
            if dep_id in seen_ids:
                continue

            # Clean up the child name: strip possessive, take first word, capitalize
            name = card_name.replace("'s", "").strip() if card_name else ""
            first_word = re.split(r"[\s\-\u2013,]+", name)[0] if name else ""
            name = first_word[0].upper() + first_word[1:].lower() if first_word else ""

            if not name:
                print(f"   Warning: found dependent_id={dep_id} but could not extract child name.")
                continue

            seen_ids.add(dep_id)
            children.append({"name": name, "dependent_id": dep_id})
            print(f"   Found: {name} -> {dep_id}")

        except Exception as e:
            print(f"   Warning: error processing Actions card: {e}")
            try:
                page.keyboard.press("Escape")
                page.wait_for_timeout(500)
            except Exception:
                pass
            continue


    if children:
        print(f"   Discovered {len(children)} child(ren) via family portal.")
        return children

    print("   No href links found on family portal — falling back to network interception...")

    # Navigate to the mybrightday dashboard for Strategy 2
    page.goto("https://mybrightday.brighthorizons.com/dashboard/parents.html")
    page.wait_for_timeout(5000)



    # Collect candidate selector li items: skip media items (a.fancybox) and month tiles
    selector_items = page.evaluate("""
        () => {
            const items = [];
            let globalIdx = 0;
            document.querySelectorAll('ul.thumbnails').forEach(list => {
                list.querySelectorAll('li').forEach(li => {
                    if (li.querySelector('a.fancybox')) { globalIdx++; return; }
                    const text = (li.innerText || li.textContent || '').trim();
                    const cleaned = text.replace(/\\s+/g, ' ');
                    if (/^[a-z]{3} \\d{4}$/i.test(cleaned)) { globalIdx++; return; }
                    items.push({ globalIdx, text });
                    globalIdx++;
                });
            });
            return items;
        }
    """)

    if not selector_items:
        print("   Warning: Could not find any candidate items to probe.")
        return []

    print(f"   Found {len(selector_items)} candidate item(s) to probe.")

    children = []
    seen_ids = set()

    for item in selector_items:
        raw_text = item['text']
        global_idx = item['globalIdx']

        # Intercept network requests fired when this tile is clicked
        captured_ids = []

        def on_request(request, _captured=captured_ids):
            m = re.search(r'dependent_id=([^&]+)', request.url)
            if m:
                _captured.append(m.group(1))

        page.on('request', on_request)

        page.evaluate("""
            (targetIdx) => {
                let globalIdx = 0;
                for (const list of document.querySelectorAll('ul.thumbnails')) {
                    for (const li of list.querySelectorAll('li')) {
                        if (globalIdx === targetIdx) {
                            const clickable = li.querySelector('div.tile') || li.querySelector('div') || li;
                            clickable.click();
                            return true;
                        }
                        globalIdx++;
                    }
                }
                return false;
            }
        """, global_idx)

        page.wait_for_timeout(2500)
        page.remove_listener('request', on_request)

        if not captured_ids:
            continue  # All Kids / months / non-child items fire no child-specific requests

        dep_id = captured_ids[0]
        if dep_id in seen_ids:
            continue

        # Clean name: drop single-letter prefix lines (e.g. "B" avatar initial)
        lines = [l.strip() for l in raw_text.splitlines() if len(l.strip()) > 1]
        name = lines[0] if lines else raw_text.strip()

        seen_ids.add(dep_id)
        children.append({"name": name, "dependent_id": dep_id})
        print(f"   Found: {name} -> {dep_id}")

    if children:
        print(f"   Discovered {len(children)} child(ren): {[c['name'] for c in children]}")
    else:
        print("   Warning: Could not auto-detect children from the dashboard.")

    return children


def scrape_photos_and_text(page):
    """
    Finds all photo attachment URLs (matching obj_attachment) on the page,
    along with their containing card/post text to extract timestamps.
    """
    js_code = """
    () => {
        const items = [];
        
        // Find all LI elements in the thumbnails container
        document.querySelectorAll('ul.thumbnails li').forEach(li => {
            // Find attachment URL inside a.fancybox (contains the full-res href)
            const a = li.querySelector('a.fancybox');
            let src = '';
            if (a) {
                src = a.getAttribute('href') || '';
            }
            if (!src || !src.includes('obj_attachment')) {
                // Fallback to background image
                const tile = li.querySelector('div.tile.pointable');
                if (tile) {
                    const style = tile.getAttribute('style') || '';
                    const match = style.match(/url\\(['"]?([^'"]+)['"]?\\)/);
                    if (match) src = match[1];
                }
            }
            
            if (src.includes('obj_attachment')) {
                // Find date overlay (format like "6/22")
                const dateEl = li.querySelector('.header span.name span') || 
                               li.querySelector('span.name span') || 
                               li.querySelector('.header span.name') || 
                               li.querySelector('span.name');
                const dateText = dateEl ? (dateEl.innerText || dateEl.textContent || '').trim() : '';
                
                // Find any card text (comment/footer) for fallback
                const footer = li.querySelector('.footer.note');
                const commentText = footer ? (footer.innerText || footer.textContent || '').trim() : '';
                
                items.push({
                    src: src,
                    dateText: dateText,
                    commentText: commentText
                });
            }
        });
        
        return items;
    }
    """
    return page.evaluate(js_code)

def download_photo_with_retries(page, full_url, retries=3):
    """Downloads photo body with retry handling."""
    for attempt in range(1, retries + 1):
        try:
            response = page.request.get(full_url, timeout=15000)
            if response.ok:
                return response
            print(f"      Warning: Failed to fetch photo {full_url} on attempt {attempt}: Status {response.status}")
        except Exception as e:
            print(f"      Warning: Error fetching photo {full_url} on attempt {attempt}: {e}")
        
        if attempt < retries:
            page.wait_for_timeout(2000 * attempt)
    return None

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Bright Horizons Scraper")
    parser.add_argument("--full", action="store_true", help="Perform a full verification sync of all historical months.")
    parser.add_argument("--verify", action="store_true", help="Perform an offline verification of downloaded files, updating metadata/timestamps.")
    
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--flat", action="store_true", help="Store files directly under downloads/[ChildName]/ (Default).")
    group.add_argument("--nest", action="store_true", help="Store files nested under downloads/[ChildName]/[YYYY]/[MM]/.")
    
    args = parser.parse_args()
    
    config = load_config()
    downloads_dir = config.get('downloads_dir', './downloads')
    
    # Determine the folder mode (flat by default)
    is_flat = not args.nest
    
    # Reorganize all existing files before continuing with verify or download
    if os.path.exists(downloads_dir):
        if is_flat:
            flatten_folders(downloads_dir)
        else:
            nest_folders(downloads_dir)
            
    if args.verify:
        run_verification(downloads_dir, is_flat=is_flat)
        return
    
    user_data_dir = config.get('user_data_dir', './user_data')
    
    os.makedirs(downloads_dir, exist_ok=True)
    manifest = load_manifest(downloads_dir)
    
    print("Launching Playwright with persistent context...")
    with sync_playwright() as p:
        # Cloudflare bypass: use installed Google Chrome channel if available, and hide automation markers
        launch_args = {
            "user_data_dir": user_data_dir,
            "headless": False,
            "viewport": {'width': 1280, 'height': 800},
            "args": ["--disable-blink-features=AutomationControlled"],
            "ignore_default_args": ["--enable-automation"]
        }
        try:
            context = p.chromium.launch_persistent_context(channel="chrome", **launch_args)
        except Exception:
            context = p.chromium.launch_persistent_context(**launch_args)
            
        page = context.pages[0] if context.pages else context.new_page()
        
        print("Checking login status...")
        page.goto("https://familyinfocenter.brighthorizons.com/home")
        page.wait_for_timeout(3000)
        
        # Check if we are redirected to a login page
        current_url = page.url
        if any(term in current_url.lower() for term in ["login", "pingone", "signin", "auth"]):
            print("=" * 70)
            print("ACTION REQUIRED: Please log in to Bright Horizons in the opened browser.")
            print("The script will automatically wait until you reach the dashboard.")
            print("=" * 70)
            
            logged_in = False
            for _ in range(300): # 5 minutes timeout
                page.wait_for_timeout(1000)
                if page.is_closed():
                    print("Browser window was closed.")
                    break
                url = page.url
                if "parents.html" in url or "dashboard" in url:
                    print("Login detected! Proceeding...")
                    logged_in = True
                    break
            
            if not logged_in:
                print("Login timeout or browser closed. Exiting.")
                context.close()
                sys.exit(1)
        else:
            print("Already logged in!")

        # Auto-detect children if not specified or empty in config
        configured_children = config.get('children', [])
        # Filter out placeholder entries (dependent_id still contains 'INSERT_')
        valid_children = [
            c for c in configured_children
            if c.get('dependent_id') and 'INSERT_' not in c.get('dependent_id', '')
        ]

        if not valid_children:
            print("\nNo valid children found in config.json. Attempting auto-detection...")
            valid_children = discover_children(page, context)
            if not valid_children:
                print("Error: Could not auto-detect children and none are configured. Exiting.")
                context.close()
                sys.exit(1)
            # Save discovered children back to config.json for future runs
            config['children'] = valid_children
            try:
                with open('config.json', 'w') as f:
                    json.dump(config, f, indent=2)
                print(f"   Saved {len(valid_children)} discovered child(ren) to config.json.")
            except Exception as e:
                print(f"   Warning: Could not save discovered children to config.json: {e}")
        else:
            print(f"\nUsing {len(valid_children)} configured child(ren): {[c['name'] for c in valid_children]}")

        for child in valid_children:
            child_name = child['name']
            dep_id = child['dependent_id']
            
            print(f"\n==========================================")
            print(f"Processing photos for {child_name}...")
            print(f"==========================================")
            
            url = f"https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id={dep_id}"
            if not safe_goto(page, url):
                print(f"Error: Could not navigate to child page for {child_name}. Skipping.")
                continue
                
            page.wait_for_timeout(5000) # wait for page to settle
            
            # 1. Discover all timeframe filter buttons (<li> elements matching 'jun 2026' pattern)
            timeframe_texts = page.evaluate("""
                () => {
                    return Array.from(document.querySelectorAll('li'))
                        .map(el => (el.innerText || el.textContent || '').trim().toLowerCase())
                        .filter(text => /^[a-z]{3}\s+\d{4}$/i.test(text));
                }
            """)
            
            if not timeframe_texts:
                print("   No timeframe buttons found on the page. Processing the default page timeline...")
                timeframe_texts = [None] # Run once for default page view
            else:
                print(f"   Found {len(timeframe_texts)} timeframes to navigate: {timeframe_texts}")
            
            # 2. Iterate through each month/year timeframe
            stop_child = False
            for tf in timeframe_texts:
                if stop_child:
                    break
                tf_year, tf_month = None, None
                if tf:
                    print(f"\n   --- Navigating to timeframe: {tf.upper()} ---")
                    tf_year, tf_month = parse_timeframe_context(tf)
                    
                    # Click timeframe button dynamically targeting the inner div.tile (Knockout handler)
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
                    """, tf)
                    
                    if not clicked:
                        print(f"   Warning: Could not click timeframe element '{tf}'. Trying locator search...")
                        try:
                            parts = tf.split()
                            if len(parts) == 2:
                                month_name, year_val = parts
                                page.locator("li").filter(has_text=re.compile(rf"{month_name}.*{year_val}", re.I)).locator("div.tile, div").first.click(timeout=5000)
                            else:
                                page.locator("li").filter(has_text=re.compile(re.escape(tf.strip()), re.I)).first.click(timeout=5000)
                        except Exception as e:
                            print(f"   Error clicking timeframe {tf}: {e}. Skipping this timeframe.")
                            continue
                            
                    page.wait_for_timeout(3000) # Wait for feed to reload
                else:
                    print("\n   --- Processing default timeline page ---")
                
                # Scroll down to load all older posts in this timeframe
                print("      Scrolling page to load historical posts...")
                scroll_to_bottom(page)
                
                # Scrape all image targets and card contents
                photo_items = scrape_photos_and_text(page)
                print(f"      Found {len(photo_items)} photo elements in this timeframe.")
                
                # Track local index for filenames on a given date
                date_indices = {}
                
                def get_next_index(date_str):
                    if date_str not in date_indices:
                        # Count existing files in the manifest for this child & date
                        existing_count = sum(
                            1 for item in manifest.values()
                            if item.get('child') == child_name and item.get('date') == date_str
                        )
                        date_indices[date_str] = existing_count
                    date_indices[date_str] += 1
                    return date_indices[date_str]
                
                last_parsed_date = None
                download_count = 0
                
                # Process the photos top-to-bottom
                for item in photo_items:
                    src = item['src']
                    date_text = item['dateText']
                    comment_text = item['commentText']
                    
                    # Get unique identifier from url
                    parsed_url = urlparse(src)
                    query_params = parse_qs(parsed_url.query)
                    obj_ids = query_params.get('obj')
                    
                    if not obj_ids:
                        import hashlib
                        obj_id = hashlib.md5(src.encode('utf-8')).hexdigest()
                    else:
                        obj_id = obj_ids[0]
                    
                    # 1. Parse date from overlay (e.g. '6/22')
                    post_date = parse_date_from_overlay(date_text, timeframe_year=tf_year)
                    
                    # 2. Fallback to comment/footer text parsing
                    if not post_date:
                        post_date = parse_date_from_text(comment_text, timeframe_year=tf_year, timeframe_month=tf_month)
                        
                    # 3. Fallback to last parsed date
                    if not post_date:
                        post_date = last_parsed_date
                        
                    # 4. Fallback to timeframe month start
                    if not post_date:
                        if tf_year and tf_month:
                            post_date = f"{tf_year:04d}-{tf_month:02d}-01"
                        else:
                            post_date = datetime.now().strftime('%Y-%m-%d')
                        
                    last_parsed_date = post_date
                    
                    # Extract year and month for sub-folder structure
                    try:
                        dt_obj = datetime.strptime(post_date, "%Y-%m-%d")
                        year_str = str(dt_obj.year)
                        month_str = f"{dt_obj.month:02d}"
                    except Exception:
                        year_str = str(tf_year) if tf_year else datetime.now().strftime('%Y')
                        month_str = f"{tf_month:02d}" if tf_month else datetime.now().strftime('%m')
                    
                    # Target folder structure
                    if is_flat:
                        dest_dir = os.path.join(downloads_dir, child_name)
                    else:
                        dest_dir = os.path.join(downloads_dir, child_name, year_str, month_str)
                    os.makedirs(dest_dir, exist_ok=True)
                    
                    # Check manifest to prevent downloading duplicates
                    # Store folder relative path in manifest to verify existence accurately
                    if obj_id in manifest:
                        filename = manifest[obj_id]['filename']
                        if is_flat:
                            expected_path = os.path.join(downloads_dir, child_name, filename)
                        else:
                            expected_path = os.path.join(downloads_dir, child_name, manifest[obj_id].get('year', year_str), manifest[obj_id].get('month', month_str), filename)
                        if os.path.exists(expected_path):
                            if not args.full:
                                print(f"      Item {obj_id} ({filename}) already exists. Stopping incremental sync for {child_name}.")
                                stop_child = True
                                break
                            continue
                    
                    # Bypassing thumbnails: Construct full resolution image link
                    # Setting key equal to the obj ID bypasses thumbnail compression
                    full_resolution_url = f"https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj={obj_id}&key={obj_id}"
                    
                    try:
                        response = download_photo_with_retries(page, full_resolution_url)
                        if response:
                            body_bytes = response.body()
                            content_type = response.headers.get('content-type', '').lower()
                            
                            # Inspect magic bytes of actual download body to get precise extension
                            extension = detect_extension(body_bytes, content_type)
                            
                            index = get_next_index(post_date)
                            filename = f"{child_name} {post_date} ({index}){extension}"
                            filepath = os.path.join(dest_dir, filename)
                            
                            # Save file
                            with open(filepath, 'wb') as f:
                                f.write(body_bytes)
                            
                            # Write short message to metadata
                            if extension.lower() in ['.jpg', '.jpeg']:
                                write_exif_comment(filepath, comment_text)
                            elif extension.lower() == '.png':
                                write_png_comment(filepath, comment_text)
                            
                            # Set file modification/access timestamp to 10:00 AM New York time (handling DST)
                            try:
                                from zoneinfo import ZoneInfo
                                dt = datetime.strptime(f"{post_date} 10:00:00", "%Y-%m-%d %H:%M:%S")
                                dt = dt.replace(tzinfo=ZoneInfo("America/New_York"))
                                timestamp = dt.timestamp()
                                os.utime(filepath, (timestamp, timestamp))
                            except Exception as time_err:
                                print(f"         Warning setting time on {filename}: {time_err}")
                                
                            # Update manifest with folder structure metadata
                            manifest[obj_id] = {
                                "child": child_name,
                                "date": post_date,
                                "year": year_str,
                                "month": month_str,
                                "filename": filename,
                                "downloaded_at": datetime.now().isoformat(),
                                "full_resolution": True,
                                "comment": comment_text
                            }
                            save_manifest(downloads_dir, manifest)
                            download_count += 1
                            
                        else:
                            print(f"      [Failed] Could not download photo {obj_id} after retries.")
                    except Exception as dl_err:
                        print(f"      Error processing photo {obj_id}: {dl_err}")
                
                if tf:
                    print(f"   Finished timeframe {tf.upper()}. Downloaded {download_count} new full-res photos.")
                else:
                    print(f"   Finished default timeline. Downloaded {download_count} new full-res photos.")
            
        print("\nAll tasks completed successfully!")
        context.close()

if __name__ == '__main__':
    main()
