# Handoff Report: Milestone 2 — Structured Step Pipeline & Asset Metadata Management

## 1. Observation

- **Existing Monolithic Pipeline:** Examined `backend/scraper_engine.py:745-920`, which contains inline timeline navigation, timeframe scanning, lazy scrolling, binary downloads, and timestamp setting.
- **Milestone 1 Core Modules:** Confirmed presence and interface contracts of `backend/dom_parser.py` (Rule 2.A timeframe parsing, Rule 2.B scoping, Rule 2.C video CSS background fallback, Rule 5 CDK auto-discovery) and `backend/security_isolation.py` (Rule 1 profile lock copying, path traversal validation, child path resolution).
- **PNG Metadata Specifications (AGENTS.md Section 3):** Requires PNG header verification (`\x89PNG\r\n\x1a\n`), duplicate keyword prevention, insertion of `tEXt` chunk at offset 33 (after `IHDR`), and big-endian uint32 packing (`struct.pack('>I', val)`) for chunk length and CRC checksum (`zlib.crc32(b"tEXt" + payload) & 0xffffffff`).
- **JPEG EXIF & Fallback Specifications:** Uses `piexif` library updating `0th` IFD `ImageDescription` (tag 270) and `Exif` IFD `UserComment` (tag 37510 with `b"ASCII\x00\x00\x00"` header). Fallback uses pure-Python JPEG COM (Comment) marker `\xff\xfe` inserted at offset 2 (after SOI `\xff\xd8`).
- **Timestamp Modification Specifications (AGENTS.md Section 4):** Requires setting file access/modification time to 10:00:00 AM New York local time using `zoneinfo.ZoneInfo("America/New_York")` and `os.utime`.

---

## 2. Logic Chain

1. **Modular Extraction Pipeline (`backend/pipeline.py`):**
   - *Observation:* `scraper_engine.py` directly handles browser logic, DOM matching, file saving, and database manifest writing in a single monolithic method.
   - *Logic:* Decoupling this into `backend/pipeline.py` allows `run_extraction_pipeline()` to be tested independently using Playwright mocks and reusable DOM parser functions from `backend/dom_parser.py`.
   - *Conclusion:* `run_extraction_pipeline()` will execute session validation, child navigation, timeframe iteration, scrolling, feed item extraction, incremental sync checking, media downloading, metadata injection, utime modification, and manifest recording.

2. **PNG Chunk Injection:**
   - *Observation:* Standard PNG files start with an 8-byte magic header (`8` bytes) followed by the `IHDR` chunk (`25` bytes total length: 4 length + 4 type + 13 data + 4 CRC).
   - *Logic:* Offset `8 + 25 = 33` is guaranteed to be immediately after `IHDR`. Inserting a `tEXt` chunk with `b"Description\x00"` payload at offset 33 conforms to ISO/IEC 15948:2004 without requiring heavy imaging dependencies.
   - *Conclusion:* Implement pure-Python `inject_png_text_chunk(file_path, comment)` using `zlib` and `struct.pack(">I", ...)`.

3. **JPEG EXIF Injection:**
   - *Observation:* JPEGs may or may not possess EXIF APP1 headers.
   - *Logic:* `piexif` provides clean EXIF dict manipulation. If `piexif` fails or EXIF is corrupted, pure-Python COM marker `\xff\xfe` injection at offset 2 provides guaranteed metadata persistence without throwing runtime exceptions.
   - *Conclusion:* Implement `inject_jpeg_exif(file_path, comment)` with try-except fallback to COM marker `\xff\xfe`.

4. **Eastern Time `os.utime` Setting:**
   - *Observation:* Host systems may run in UTC or non-Eastern local timezones. Using `time.mktime()` introduces host timezone bias.
   - *Logic:* Creating a `datetime` object at 10:00:00 AM, attaching `ZoneInfo("America/New_York")`, and calling `.timestamp()` guarantees standard vs daylight saving time resolution regardless of the runner host's local timezone.
   - *Conclusion:* Implement `set_eastern_utime(file_path, date_str)` returning epoch timestamp and invoking `os.utime`.

---

## 3. Caveats

- **Network Dependency in E2E Pipeline:** While unit tests for metadata, utime, and DOM parsing are 100% offline, `run_extraction_pipeline` end-to-end testing relies on Playwright browser mocks or a live test account.
- **Corrupted Non-Standard Image Binaries:** Extremely truncated or non-standard PNG/JPEG files (less than 33 bytes for PNG or missing SOI for JPEG) will raise `ValueError` during metadata injection, which must be caught gracefully by the pipeline.

---

## 4. Conclusion

Milestone 2 design is fully specified and ready for implementation.
- `backend/pipeline.py` will expose `run_extraction_pipeline`, `inject_png_text_chunk`, `inject_jpeg_exif`, and `set_eastern_utime`.
- `backend/tests/test_pipeline.py` will provide isolated unit tests for PNG/JPEG metadata, Eastern time utime modification, and mocked pipeline execution.

---

## 5. Verification Method

To independently verify the analysis and future implementation:
1. **Inspect Analysis Report:** Review `.agents/explorer_m2/analysis.md`.
2. **Execute Unit Tests:** Run pytest on existing test suite to ensure workspace integrity:
   ```bash
   pytest backend/tests/
   ```
3. **Verify PNG Injection Logic:**
   - Run python check for PNG header (`\x89PNG\r\n\x1a\n`) and offset 33 chunk type (`tEXt`).
4. **Verify Eastern Timezone Epoch:**
   - Check `set_eastern_utime` for winter (`2026-01-15` -> 15:00 UTC) vs summer (`2026-07-15` -> 14:00 UTC).
