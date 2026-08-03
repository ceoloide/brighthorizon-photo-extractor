## 2026-07-31T09:44:19-04:00
You are the Implementation Worker for Milestone 2: Structured Step Pipeline & Asset Metadata Management.

Task:
1. Implement `backend/pipeline.py` adhering to specifications in `.agents/explorer_m2/analysis.md`:
   - `inject_png_text_chunk(file_path, comment)`: Pure-Python PNG `tEXt` metadata chunk injection at offset 33 (after `IHDR`), excluding duplicates, big-endian length & CRC32 (`zlib.crc32`).
   - `inject_jpeg_exif(file_path, comment)`: EXIF injection using `piexif` (`0th` IFD `ImageDescription` tag 270, `Exif` IFD `UserComment` tag 37510 with `b"ASCII\x00\x00\x00"` header), with pure-Python JPEG `COM` marker (`\xff\xfe`) fallback at offset 2.
   - `set_eastern_utime(file_path, date_str_or_dt)`: Sets file access and modification times (`os.utime`) strictly to 10:00:00 AM New York local time using `zoneinfo.ZoneInfo("America/New_York")` (dynamic EST/EDT offset).
   - `run_extraction_pipeline(page, child_name, dependent_id, output_dir, start_date, log_callback)`: Structured extraction workflow (session check, child navigation, timeframe iteration, scrolling, feed item parsing via `dom_parser.py`, binary downloading, metadata injection, utime modification, manifest recording in `downloads/manifest.json`).

2. Implement unit test suite `backend/tests/test_pipeline.py`:
   - PNG `tEXt` chunk injection and reading.
   - JPEG EXIF injection and fallback COM marker injection.
   - Eastern Time `os.utime` modification (verifying winter EST vs summer EDT epoch timestamps).
   - Mocked Playwright pipeline execution.

3. Run `.venv/bin/pytest backend/tests/ -v` and verify all tests pass 100%.

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A Forensic Auditor will independently verify your work.

Write your report to `.agents/worker_m2/handoff.md`.
