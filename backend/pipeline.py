# SPDX-License-Identifier: MIT
"""
Pipeline Module for Bright Horizons Photo Extractor.

Encapsulates:
- Pure-Python PNG tEXt metadata chunk injection.
- JPEG EXIF comment injection with pure-Python COM marker fallback.
- Eastern Time file modification (os.utime).
- Step-by-step media extraction pipeline.
Spec reference: .agents/explorer_m2/analysis.md
"""

import os
import re
import json
import zlib
import struct
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Optional, Dict, Any, Callable, Union, List

try:
    import piexif
except ImportError:
    piexif = None

from backend import dom_parser
from backend import security_isolation


# =============================================================================
# 1. Asset Metadata Management Functions
# =============================================================================

def inject_png_text_chunk(file_path: str, comment: str) -> None:
    """
    Pure-Python PNG tEXt metadata chunk injection at offset 33 (after IHDR).
    Excludes duplicate 'Description' keyword chunks, formats length and CRC32
    checksum using big-endian unsigned 32-bit integers.
    """
    with open(file_path, "rb") as f:
        data = f.read()

    png_header = b"\x89PNG\r\n\x1a\n"
    if len(data) < 33 or not data.startswith(png_header):
        raise ValueError("Invalid PNG file header")

    # Read IHDR chunk
    ihdr_len = struct.unpack(">I", data[8:12])[0]
    ihdr_type = data[12:16]
    if ihdr_type != b"IHDR":
        raise ValueError("Invalid PNG structure: missing IHDR chunk")

    ihdr_end = 8 + 4 + 4 + ihdr_len + 4  # Header(8) + Len(4) + Type(4) + Data(ihdr_len) + CRC(4)

    # Parse and filter chunks after IHDR
    pos = ihdr_end
    chunks_after_ihdr = []
    while pos + 8 <= len(data):
        chunk_len = struct.unpack(">I", data[pos:pos+4])[0]
        chunk_type = data[pos+4:pos+8]
        chunk_data_end = pos + 8 + chunk_len
        chunk_end = chunk_data_end + 4

        if chunk_end > len(data):
            break  # Truncated chunk

        chunk_payload = data[pos+8:chunk_data_end]

        # Check for existing Description tEXt chunk
        if chunk_type == b"tEXt" and chunk_payload.startswith(b"Description\x00"):
            # Omit duplicate Description tEXt chunk
            pos = chunk_end
            continue

        chunks_after_ihdr.append(data[pos:chunk_end])
        pos = chunk_end

    # Construct new tEXt chunk
    keyword = b"Description"
    text_bytes = comment.encode("utf-8")
    payload = keyword + b"\x00" + text_bytes
    chunk_type = b"tEXt"

    len_bytes = struct.pack(">I", len(payload))
    crc_val = zlib.crc32(chunk_type + payload) & 0xffffffff
    crc_bytes = struct.pack(">I", crc_val)

    new_chunk = len_bytes + chunk_type + payload + crc_bytes

    # Reassemble PNG file data
    new_data = data[:ihdr_end] + new_chunk + b"".join(chunks_after_ihdr)

    with open(file_path, "wb") as f:
        f.write(new_data)


def _inject_jpeg_com_fallback(file_path: str, comment: str) -> None:
    """
    Pure-Python JPEG COM (Comment) marker (\xff\xfe) fallback injection at offset 2.
    """
    with open(file_path, "rb") as f:
        data = f.read()

    if len(data) < 2 or not data.startswith(b"\xff\xd8"):
        raise ValueError("Invalid JPEG file header")

    payload = comment.encode("utf-8")
    marker_length = len(payload) + 2
    com_chunk = b"\xff\xfe" + struct.pack(">H", marker_length) + payload

    new_data = data[:2] + com_chunk + data[2:]

    with open(file_path, "wb") as f:
        f.write(new_data)


def inject_jpeg_exif(file_path: str, comment: str) -> None:
    """
    JPEG EXIF injection using piexif (0th IFD ImageDescription tag 270, Exif IFD
    UserComment tag 37510 with ASCII header), with pure-Python COM marker fallback.
    """
    if piexif is None:
        _inject_jpeg_com_fallback(file_path, comment)
        return

    try:
        try:
            exif_dict = piexif.load(file_path)
        except Exception:
            exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

        if "0th" not in exif_dict or not isinstance(exif_dict["0th"], dict):
            exif_dict["0th"] = {}
        if "Exif" not in exif_dict or not isinstance(exif_dict["Exif"], dict):
            exif_dict["Exif"] = {}

        exif_dict["0th"][piexif.ImageIFD.ImageDescription] = comment.encode("utf-8")
        exif_dict["Exif"][piexif.ExifIFD.UserComment] = b"ASCII\x00\x00\x00" + comment.encode("utf-8")

        exif_bytes = piexif.dump(exif_dict)
        piexif.insert(exif_bytes, file_path)
    except Exception:
        # Fallback to pure-Python COM marker on piexif error
        _inject_jpeg_com_fallback(file_path, comment)


def set_eastern_utime(file_path: str, date_str_or_dt: Union[str, datetime]) -> float:
    """
    Sets file access and modification times (os.utime) strictly to 10:00:00 AM
    New York local time using zoneinfo.ZoneInfo("America/New_York") (dynamic EST/EDT offset).
    Returns the calculated epoch timestamp (seconds).
    """
    if isinstance(date_str_or_dt, str):
        date_clean = date_str_or_dt.strip()
        try:
            dt = datetime.strptime(date_clean[:10], "%Y-%m-%d")
        except ValueError:
            iso_str = dom_parser.parse_date_overlay(date_clean)
            dt = datetime.strptime(iso_str, "%Y-%m-%d")
    elif isinstance(date_str_or_dt, datetime):
        dt = date_str_or_dt
    else:
        raise TypeError("date_str_or_dt must be str or datetime")

    dt_10am = dt.replace(hour=10, minute=0, second=0, microsecond=0)
    dt_eastern = dt_10am.replace(tzinfo=ZoneInfo("America/New_York"))
    epoch_sec = dt_eastern.timestamp()

    os.utime(file_path, (epoch_sec, epoch_sec))
    return epoch_sec


# =============================================================================
# 2. Step Extraction Pipeline
# =============================================================================

def run_extraction_pipeline(
    page: Any,
    child_name: str,
    dependent_id: str,
    output_dir: str,
    start_date: Optional[str] = None,
    sync_mode: str = "incremental",
    manifest_cache: Optional[Dict[str, Any]] = None,
    cancel_checker: Optional[Callable[[], bool]] = None,
    logger: Optional[Callable[[str], None]] = None,
    log_callback: Optional[Callable[[str], None]] = None
) -> Dict[str, Any]:
    """
    Structured extraction workflow for a single child:
    1. Session verification (aborts if login screen detected).
    2. Child timeline navigation.
    3. Timeframe iteration & Knokout tile clicking.
    4. Lazy scrolling & feed item parsing via dom_parser.py.
    5. Media downloading via Playwright context.
    6. Asset metadata injection & Eastern Time utime setting.
    7. Manifest recording & file writing.
    """
    _logger = log_callback or logger

    def log(msg: str):
        if _logger:
            _logger(msg)

    # 1. Session Verification
    current_url = getattr(page, "url", "").lower()
    if any(k in current_url for k in ["login", "sso", "sign-in"]):
        log(f"Unauthenticated session detected on URL: {page.url}")
        raise RuntimeError(f"Unauthenticated session: redirected to {page.url}")

    # 2. Child Navigation
    target_url = f"https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id={dependent_id}"
    log(f"Navigating to child timeline for {child_name} (ID: {dependent_id}): {target_url}")
    
    if current_url != target_url.lower():
        page.goto(target_url, wait_until="domcontentloaded")
        page.wait_for_timeout(1000)

    # Re-verify session post-navigation
    new_url = getattr(page, "url", "").lower()
    if any(k in new_url for k in ["login", "sso", "sign-in"]):
        log(f"Unauthenticated session detected after navigation to {new_url}")
        raise RuntimeError(f"Unauthenticated session: redirected to {new_url}")

    dom_parser.dismiss_cdk_overlays(page)

    # 3. Discover Timeframe Links
    tf_links = dom_parser.parse_timeframe_links(page)
    log(f"Discovered {len(tf_links)} timeframe items for {child_name}")
    page.wait_for_timeout(15000)  # 15s delay after finding timeframe month links

    # Initialize manifest state
    manifest_path = os.path.join(output_dir, "manifest.json")
    if manifest_cache is not None:
        manifest = dict(manifest_cache)
    elif os.path.exists(manifest_path):
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            manifest = {}
    else:
        manifest = {}

    downloaded_count = 0
    skipped_count = 0
    processed_count = 0

    if cancel_checker and cancel_checker():
        log("Extraction cancelled prior to timeframe processing.")
        return {
            "status": "cancelled",
            "child_name": child_name,
            "dependent_id": dependent_id,
            "processed_count": processed_count,
            "downloaded_count": downloaded_count,
            "skipped_count": skipped_count,
            "manifest": manifest,
        }

    def save_manifest_to_disk():
        os.makedirs(output_dir, exist_ok=True)
        try:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest, f, indent=2)
        except Exception as e:
            log(f"Error saving manifest to {manifest_path}: {e}")

    # If no timeframe links were found, attempt reading current visible feed directly
    if not tf_links:
        tf_links = [{"text": "current", "year": datetime.now().year, "locator": None}]

    found_previously_downloaded = False
    reached_custom_start_date = False

    for tf_item in tf_links:
        if cancel_checker and cancel_checker():
            log("Extraction cancelled during timeframe iteration.")
            save_manifest_to_disk()
            return {
                "status": "cancelled",
                "child_name": child_name,
                "dependent_id": dependent_id,
                "processed_count": processed_count,
                "downloaded_count": downloaded_count,
                "skipped_count": skipped_count,
                "manifest": manifest,
            }

        tf_text = tf_item.get("text", "")
        log(f"Processing timeframe tile: {tf_text}")

        # Start Date Filter Check on Month Level
        if sync_mode in ("incremental", "custom") and start_date:
            m_end = dom_parser.get_month_end_date(tf_text)
            if m_end and m_end < start_date:
                log(f"Timeframe month '{tf_text}' (end date: {m_end}) is prior to custom start date {start_date}. Halting month scan for {child_name}.")
                reached_custom_start_date = True
                break

        if tf_item.get("locator") is not None:
            dom_parser.click_timeframe_tile(page, tf_item)
            page.wait_for_timeout(2000)

        # 4. Lazy Scroll
        for _ in range(2):
            try:
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(800)
                page.evaluate("window.scrollBy(0, -500)")
                page.wait_for_timeout(400)
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(800)
            except Exception as e:
                log(f"Scroll evaluation notice: {e}")

        # 5. Extract Feed Items
        tf_year = tf_item.get("year")
        if not tf_year:
            m_year = re.search(r"\b(20\d{2})\b", tf_text)
            tf_year = int(m_year.group(1)) if m_year else datetime.now().year

        feed_items = dom_parser.extract_feed_items(page, timeframe_year=tf_year)
        log(f"Extracted {len(feed_items)} feed items for timeframe '{tf_text}'")
        if not feed_items:
            continue

        # Ensure all feed items have date_str resolved
        for item in feed_items:
            if not item.get("date_str"):
                item["date_str"] = f"{datetime.now().year:04d}-01-01"

        # Sort feed items descending by date only in incremental/custom modes
        if sync_mode in ("incremental", "custom"):
            feed_items.sort(key=lambda x: x.get("date_str", ""), reverse=True)

        download_queue = []
        seen_in_queue = set()
        max_downloaded_date = None

        if sync_mode in ("incremental", "custom"):
            # Step 1: Check for already downloaded pictures
            for item in feed_items:
                obj_id = item.get("obj_id")
                if not obj_id:
                    continue
                if obj_id in manifest:
                    found_previously_downloaded = True
                    item_date = item.get("date_str")
                    if max_downloaded_date is None or (item_date and item_date > max_downloaded_date):
                        max_downloaded_date = item_date

            # Step 2: Check for reaching custom start date
            if (sync_mode == "custom" or start_date) and start_date:
                for item in feed_items:
                    item_date = item.get("date_str")
                    if item_date and item_date < start_date:
                        reached_custom_start_date = True
                        break

            # Step 3: Remove already downloaded items, all that are older than max_downloaded_date,
            # and all that are older than custom start date
            for item in feed_items:
                obj_id = item.get("obj_id")
                if not obj_id:
                    continue
                item_date = item.get("date_str")

                if (sync_mode == "custom" or start_date) and start_date and item_date and item_date < start_date:
                    log(f"[Cutoff / Start Date] Item {obj_id[:8]} ({item_date}) is prior to custom start date {start_date}. Skipping.")
                    skipped_count += 1
                    continue

                if obj_id in manifest:
                    log(f"[Cutoff / Previously Downloaded] Item {obj_id[:8]} ({item_date}) already in manifest. Skipping.")
                    skipped_count += 1
                    continue

                if max_downloaded_date and item_date and item_date < max_downloaded_date:
                    log(f"[Cutoff / Older Than Downloaded] Item {obj_id[:8]} ({item_date}) is older than downloaded cutoff ({max_downloaded_date}). Skipping.")
                    skipped_count += 1
                    continue

                if obj_id in seen_in_queue:
                    continue
                seen_in_queue.add(obj_id)
                download_queue.append(item)
        else:
            for item in feed_items:
                obj_id = item.get("obj_id")
                if not obj_id:
                    continue
                item_date = item.get("date_str")
                if start_date and item_date < start_date:
                    log(f"Item {obj_id} date {item_date} is prior to start_date {start_date}, skipping.")
                    skipped_count += 1
                    continue
                if obj_id in manifest:
                    skipped_count += 1
                    continue
                if obj_id in seen_in_queue:
                    continue
                seen_in_queue.add(obj_id)
                download_queue.append(item)

        for item in download_queue:
            if cancel_checker and cancel_checker():
                log("Extraction cancelled during feed item processing.")
                save_manifest_to_disk()
                return {
                    "status": "cancelled",
                    "child_name": child_name,
                    "dependent_id": dependent_id,
                    "processed_count": processed_count,
                    "downloaded_count": downloaded_count,
                    "skipped_count": skipped_count,
                    "manifest": manifest,
                }

            obj_id = item.get("obj_id")
            if not obj_id:
                continue

            date_str = item.get("date_str") or f"{datetime.now().year:04d}-01-01"
            is_video = item.get("is_video", False)
            download_url = item.get("download_url")
            raw_comment = item.get("comment", "")

            if not download_url:
                log(f"No download URL for item {obj_id}, skipping.")
                continue

            # 7. Media Downloading
            try:
                req_headers = {
                    "Referer": "https://mybrightday.brighthorizons.com/dashboard/parents.html",
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
                }
                response = page.request.get(download_url, headers=req_headers, timeout=120000)
                if not response or not response.ok:
                    status_code = getattr(response, "status", "unknown")
                    log(f"HTTP GET failed for {download_url} with status {status_code}")
                    continue
                body_bytes = response.body()
                try:
                    json_data = json.loads(body_bytes.decode("utf-8"))
                    if isinstance(json_data, dict) and "signed_url" in json_data:
                        signed_url = json_data["signed_url"]
                        media_resp = page.request.get(signed_url, headers={"User-Agent": req_headers["User-Agent"]}, timeout=120000)
                        if media_resp and media_resp.ok:
                            body_bytes = media_resp.body()
                except Exception:
                    pass
            except Exception as e:
                log(f"Error fetching media bytes for {obj_id}: {e}")
                continue

            # Infer extension
            if body_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                ext = ".png"
            elif body_bytes.startswith(b"\xff\xd8"):
                ext = ".jpg"
            elif is_video or b"ftyp" in body_bytes[:32]:
                ext = ".mp4"
            else:
                ext = ".mp4" if is_video else ".jpg"

            filename = f"{date_str}_{obj_id}{ext}"
            target_path = security_isolation.resolve_child_output_path(output_dir, child_name, filename)

            # Ensure parent directories exist
            os.makedirs(os.path.dirname(target_path), exist_ok=True)

            with open(target_path, "wb") as f:
                f.write(body_bytes)

            # 8. Asset Metadata Injection
            comment_text = f"Bright Horizons photo for {child_name} on {date_str}"
            if raw_comment:
                comment_text += f": {raw_comment}"

            try:
                if ext == ".png":
                    inject_png_text_chunk(target_path, comment_text)
                elif ext in [".jpg", ".jpeg"]:
                    inject_jpeg_exif(target_path, comment_text)
            except Exception as e:
                log(f"Metadata injection warning for {filename}: {e}")

            # 9. Eastern utime Modification
            try:
                set_eastern_utime(target_path, date_str)
            except Exception as e:
                log(f"utime modification warning for {filename}: {e}")

            # 10. Manifest Recording
            manifest[obj_id] = {
                "obj_id": obj_id,
                "child": child_name,
                "dependent_id": dependent_id,
                "date": date_str,
                "original_filename": filename,
                "storage_path": target_path,
                "comment": comment_text,
                "file_size": len(body_bytes),
                "is_video": is_video,
                "downloaded_at": datetime.now().isoformat(),
            }

            downloaded_count += 1
            processed_count += 1

        # Explicit continuation check after all downloads in the timeframe are processed
        if sync_mode in ("incremental", "custom"):
            if found_previously_downloaded:
                log(f"Incremental sync: Found previously downloaded pictures in timeframe '{tf_text}'. Halting feed scan for {child_name}.")
                break
            if reached_custom_start_date:
                log(f"Custom sync: Reached custom start date cutoff ({start_date}) in timeframe '{tf_text}'. Halting feed scan for {child_name}.")
                break

    # Save manifest back to disk
    os.makedirs(output_dir, exist_ok=True)
    try:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
    except Exception as e:
        log(f"Error saving manifest to {manifest_path}: {e}")

    return {
        "status": "completed",
        "child_name": child_name,
        "dependent_id": dependent_id,
        "processed_count": processed_count,
        "downloaded_count": downloaded_count,
        "skipped_count": skipped_count,
        "manifest": manifest,
    }
