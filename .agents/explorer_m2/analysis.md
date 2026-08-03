# Milestone 2 Analysis: Structured Step Pipeline & Asset Metadata Management

## Executive Summary
This report provides the architectural requirements, design specifications, and implementation guidelines for Milestone 2: `backend/pipeline.py` and its test suite `backend/tests/test_pipeline.py`. 

Milestone 2 encapsulates the core step-by-step extraction pipeline, pure-Python PNG `tEXt` metadata chunk injection, JPEG EXIF comment injection with a pure-Python fallback, Eastern Time file modification (`os.utime`), and tenant manifest recording.

---

## 1. `backend/pipeline.py` Step Workflow Architecture

The extraction pipeline replaces the monolithic implementation in `backend/scraper_engine.py` with a modular, testable pipeline function leveraging `backend/dom_parser.py` and `backend/security_isolation.py`.

### 1.1 Signature & Return Contract
```python
def run_extraction_pipeline(
    page: Page,
    child_name: str,
    dependent_id: str,
    output_dir: str,
    start_date: Optional[str] = None,
    sync_mode: str = "incremental",
    manifest_cache: Optional[Dict[str, Any]] = None,
    cancel_checker: Optional[Callable[[], bool]] = None,
    logger: Optional[Callable[[str], None]] = None
) -> Dict[str, Any]:
```

### 1.2 Step Sequence Details

```
 [1. Session Verification] ──► [2. Child Timeline Navigation] ──► [3. Timeframe Iteration]
                                                                        │
 ┌──────────────────────────────────────────────────────────────────────┘
 ▼
 [4. Click Month Tile] ──► [5. Lazy Feed Scroll] ──► [6. Feed Scoped Item Extraction]
                                                               │
 ┌─────────────────────────────────────────────────────────────┘
 ▼
 [7. Incremental & Date Filtering] ──► [8. Download Media Bytes]
                                              │
 ┌────────────────────────────────────────────┘
 ▼
 [9. Pure-Python Metadata Injection (PNG/JPEG)] ──► [10. NY Eastern utime Modification]
                                                               │
 ┌─────────────────────────────────────────────────────────────┘
 ▼
 [11. Path Isolation & Manifest Recording]
```

1. **Session Verification:**
   - Query `page.url` and page state. If redirected to login/SSO (`login` or `sso` in `page.url`), abort and raise an unauthenticated session exception.
2. **Child Timeline Navigation:**
   - Direct `page.goto(f"https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id={dependent_id}")`.
   - Optionally click top child selection tile matching `child_name` if present.
3. **Timeframe Links Discovery:**
   - Call `dom_parser.parse_timeframe_links(page)`. Wait dynamically up to 30s for month `<li>` elements matching `^[a-z]{3}\s+\d{4}$` to render.
4. **Timeframe Month Iteration:**
   - For each discovered timeframe (e.g. `jun 2026`):
     a. Check `cancel_checker()`; return early if cancellation requested.
     b. Execute `dom_parser.click_timeframe_tile(page, tf_item)` targeting inner `div.tile.pointable` (Rule 2.A).
     c. Wait 2-3 seconds for Knockout.js state update.
5. **Lazy Scrolling:**
   - Perform iterative scrolling (`window.scrollTo(0, document.body.scrollHeight)`, pause, shake scroll `window.scrollBy(0, -600)`, scroll down) to trigger lazy-loaded feed items.
6. **Feed Item Extraction:**
   - Call `dom_parser.extract_feed_items(page, timeframe_year=tf_year)`, which strictly scopes queries inside `div.well.left-panel.pull-left` (Rule 2.B) and handles video background CSS fallback (Rule 2.C).
7. **Incremental Sync & Custom Date Filtering:**
   - Check if `obj_id` exists in `manifest_cache`. If `sync_mode == "incremental"` and `obj_id` is already present, log notification and halt further feed scanning for this child.
   - If `start_date` (`YYYY-MM-DD`) is provided and item `date_str < start_date`, skip item.
8. **Media Downloading:**
   - Fetch media payload using Playwright context request: `response = page.request.get(download_url)`.
   - Infer extension (`png`, `jpg`, `mp4`, `mov`) from magic bytes and HTTP `content-type`.
9. **Asset Metadata Injection:**
   - Construct comment string: `f"Bright Horizons photo for {child_name} on {date_str}"`.
   - If PNG: invoke `inject_png_text_chunk(file_path, comment)`.
   - If JPEG: invoke `inject_jpeg_exif(file_path, comment)`.
10. **Eastern Time `os.utime` Setting:**
    - Invoke `set_eastern_utime(file_path, date_str)` to stamp file modification time to 10:00:00 AM NY Eastern Time (`ZoneInfo("America/New_York")`).
11. **Path Isolation & Manifest Recording:**
    - Resolve target file path using `security_isolation.resolve_child_output_path(output_dir, child_name, filename)`.
    - Record entry in manifest dictionary (`obj_id`, `child`, `date`, `original_filename`, `storage_path`, `comment`, `file_size`).

---

## 2. Pure-Python PNG `tEXt` Chunk Metadata Injection

### 2.1 Rule Compliance (AGENTS.md Section 3)
- **Header Check:** Verify PNG magic bytes: `b"\x89PNG\r\n\x1a\n"` (8 bytes).
- **Duplicate Keyword Prevention:** Parse existing chunks to check if a `tEXt` chunk with keyword `Description` already exists.
- **`IHDR` Offset Insertion:** Insert the new `tEXt` chunk at offset **33** (immediately following `IHDR` length [4B] + type [4B] + data [13B] + CRC [4B] = 25 bytes + 8 header bytes).
- **Big-Endian Encoding:** Chunk length (4 bytes) and CRC checksum (4 bytes) must be packed using `struct.pack(">I", value)`.

### 2.2 Binary Layout Math
- PNG Signature: `0..7` (8 bytes) -> `\x89PNG\r\n\x1a\n`
- `IHDR` Chunk: `8..32` (25 bytes):
  - Length: `\x00\x00\x00\x0d` (13)
  - Type: `IHDR` (4 bytes)
  - Data: 13 bytes
  - CRC: `\xXX\xXX\xXX\xXX` (4 bytes)
- Offset 33: Target insertion point.

### 2.3 `tEXt` Payload Structure
```
+-------------------+--------------------+------------------+-------------------+
|  Length (4 Bytes) |  Chunk Type (4B)   | Data Payload     |  CRC Checksum (4B)|
|  struct.pack('>I')|  b"tEXt"           | Keyword + \x00 + |  zlib.crc32 over  |
|                   |                    | Text Value       |  Type + Data      |
+-------------------+--------------------+------------------+-------------------+
```
- Keyword: `b"Description"`
- Separator: `b"\x00"`
- Value: `comment.encode("utf-8")`
- Data Payload = `b"Description\x00" + comment.encode("utf-8")`
- Length = `len(Data Payload)`
- CRC Checksum = `zlib.crc32(b"tEXt" + Data Payload) & 0xffffffff`

### 2.4 Duplicate Keyword Handling
When scanning an existing PNG file:
1. Iterate over chunks starting at offset 33.
2. Read 4-byte length $L$, 4-byte type $T$.
3. If $T == b"tEXt"`: read $L$ bytes of payload. If payload starts with `b"Description\x00"`, remove or replace existing chunk rather than appending a duplicate `tEXt` chunk.
4. If keyword is not found, insert new `tEXt` chunk at offset 33.

---

## 3. JPEG EXIF Comment Injection with Fallback

### 3.1 Primary Strategy (`piexif`)
Inject metadata into both EXIF `0th` IFD `ImageDescription` (tag 270) and `Exif` IFD `UserComment` (tag 37510).

```python
import piexif

def inject_jpeg_exif(file_path: str, comment: str) -> None:
    try:
        exif_dict = piexif.load(file_path)
    except Exception:
        exif_dict = {"0th": {}, "Exif": {}, "GPS": {}, "1st": {}, "thumbnail": None}

    if "0th" not in exif_dict: exif_dict["0th"] = {}
    if "Exif" not in exif_dict: exif_dict["Exif"] = {}

    # ImageDescription (ASCII / UTF-8)
    exif_dict["0th"][piexif.ImageIFD.ImageDescription] = comment.encode("utf-8")

    # UserComment (EXIF standard requires b"ASCII\x00\x00\x00" header)
    exif_dict["Exif"][piexif.ExifIFD.UserComment] = b"ASCII\x00\x00\x00" + comment.encode("utf-8")

    exif_bytes = piexif.dump(exif_dict)
    piexif.insert(exif_bytes, file_path)
```

### 3.2 Pure-Python COM Marker Fallback
If `piexif` raises an exception (e.g. invalid/corrupted EXIF header or missing library), fall back to injecting a standard JPEG `COM` (Comment) marker `\xff\xfe`:
- Check for JPEG Start of Image (SOI) marker `b"\xff\xd8"` at offset 0.
- Payload = `comment.encode("utf-8")`.
- Marker Length = `len(payload) + 2` (length field itself is 2 bytes).
- COM Chunk = `b"\xff\xfe" + struct.pack(">H", marker_length) + payload`.
- Insert at offset 2 (immediately after SOI).

---

## 4. Eastern Time `os.utime` Modification

### 4.1 Specification (AGENTS.md Section 4)
- **Target Local Time:** Exactly `10:00 AM` (10:00:00).
- **Timezone:** `zoneinfo.ZoneInfo("America/New_York")`.
- **Dynamic DST:** Handles Eastern Standard Time (EST, UTC-5) vs Eastern Daylight Time (EDT, UTC-4) based on post date.
- **Function:** `set_eastern_utime(file_path: str, date_or_dt: str | datetime) -> None`.

### 4.2 Epoch Calculation Logic
```python
from datetime import datetime
from zoneinfo import ZoneInfo
import os

def set_eastern_utime(file_path: str, date_or_dt: str | datetime) -> float:
    if isinstance(date_or_dt, str):
        dt = datetime.strptime(date_or_dt.strip(), "%Y-%m-%d")
    else:
        dt = date_or_dt

    dt_10am = dt.replace(hour=10, minute=0, second=0, microsecond=0)
    dt_eastern = dt_10am.replace(tzinfo=ZoneInfo("America/New_York"))
    epoch_sec = dt_eastern.timestamp()

    os.utime(file_path, (epoch_sec, epoch_sec))
    return epoch_sec
```

### 4.3 Validation Examples
- Winter Date `2026-01-15` (EST, UTC-5): 10:00:00 AM EST = 15:00:00 UTC -> Epoch `1768489200.0`.
- Summer Date `2026-07-15` (EDT, UTC-4): 10:00:00 AM EDT = 14:00:00 UTC -> Epoch `1784124000.0`.

---

## 5. Unit Test Plan for `backend/tests/test_pipeline.py`

### 5.1 Test Suite Structure

| Test Function | Target Module/Method | Objective / Verification |
|---------------|----------------------|--------------------------|
| `test_inject_png_text_chunk_valid` | `inject_png_text_chunk` | Verify header, insertion at offset 33, payload `Description\x00`, CRC32 checksum, valid image decoding. |
| `test_inject_png_text_chunk_duplicate` | `inject_png_text_chunk` | Verify re-injecting comment updates existing keyword block without duplicate chunks. |
| `test_inject_png_invalid_header` | `inject_png_text_chunk` | Verify non-PNG bytes raise `ValueError`. |
| `test_inject_jpeg_exif_piexif` | `inject_jpeg_exif` | Verify `piexif` load reads `ImageDescription` and `UserComment`. |
| `test_inject_jpeg_exif_fallback` | `inject_jpeg_exif` | Verify pure-Python COM marker `\xff\xfe` injection when `piexif` fails. |
| `test_set_eastern_utime_est` | `set_eastern_utime` | Verify winter date setting 10:00 AM EST (15:00 UTC). |
| `test_set_eastern_utime_edt` | `set_eastern_utime` | Verify summer date setting 10:00 AM EDT (14:00 UTC). |
| `test_run_extraction_pipeline_full_sync` | `run_extraction_pipeline` | Mock Playwright page & DOM; verify full feed extraction, file saving, metadata, and manifest output. |
| `test_run_extraction_pipeline_incremental` | `run_extraction_pipeline` | Mock existing `obj_id` in manifest; verify early return in incremental mode. |
| `test_run_extraction_pipeline_start_date` | `run_extraction_pipeline` | Mock feed items older than `start_date`; verify old items are skipped. |
| `test_run_extraction_pipeline_unauthenticated` | `run_extraction_pipeline` | Mock login page redirect; verify unauthenticated session exception raised. |
| `test_run_extraction_pipeline_cancellation` | `run_extraction_pipeline` | Mock cancel callback returning `True`; verify graceful abort. |

---

## 6. Implementation Readiness & Summary Matrix

| Milestone 2 Task | File Location | Key Dependencies | Compliance Standard |
|------------------|---------------|------------------|---------------------|
| Step Pipeline Workflow | `backend/pipeline.py` | `dom_parser.py`, `security_isolation.py` | Scoped left panel (2.B), Knockout tile click (2.A) |
| Pure-Python PNG Chunk | `backend/pipeline.py` | `zlib`, `struct` | AGENTS.md Sec 3 (offset 33, big-endian uint32, CRC) |
| JPEG EXIF & COM Fallback | `backend/pipeline.py` | `piexif` | EXIF 0th/Exif IFD tags & COM `\xff\xfe` fallback |
| Eastern Time utime | `backend/pipeline.py` | `zoneinfo.ZoneInfo("America/New_York")` | AGENTS.md Sec 4 (10:00 AM EST/EDT) |
| Pipeline Unit Tests | `backend/tests/test_pipeline.py` | `pytest`, `unittest.mock` | Full isolated & mocked test coverage |
