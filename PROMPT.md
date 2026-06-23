# System Reconstruction Prompt

You can copy and paste the prompt below into any advanced Large Language Model (LLM) to recreate the final version of this script.

---

```text
Write a robust Python 3.9+ web scraper script using Playwright (`sync_api`) to extract full-resolution photos and videos of children from a Bright Horizons parent portal.

### Dependencies
- The script must support **`uv run`** by declaring its dependencies natively at the top of the file using a **PEP 723 inline script metadata** block:
  ```python
  # /// script
  # requires-python = ">=3.9"
  # dependencies = [
  #     "playwright",
  #     "piexif",
  # ]
  # ///
  ```
- Use `playwright` for page interaction.
- Use `piexif` to write EXIF comments into JPEG images.
- Use native standard library modules like `struct`, `zlib`, `json`, `os`, `sys`, `time`, `re`, `argparse`, and `zoneinfo` (specifically `ZoneInfo` for timezone offsets). No other third-party dependencies are allowed.

### Core Configuration
The script must load parameters from a `config.json` file in the working directory:
```json
{
  "children": [
    { "name": "Byron", "dependent_id": "673e065a9d37c9fab2483b2d" },
    { "name": "Catherine", "dependent_id": "6322019106aa0d39b230f4a0" }
  ],
  "user_data_dir": "./user_data",
  "downloads_dir": "./downloads"
}
```

### Sync and Organization Modes of Operation
Support three distinct sync modes and two layout organization modes using `argparse`:
1. **Incremental Sync (Default Mode)**
   Processes each child starting from the most recent month and going backwards. The moment it hits a photo/video that is already in the manifest and exists on disk, it stops processing that child immediately and moves to the next child.
2. **Full Verification Sync (triggered via `--full` flag)**
   Goes through all historical months and elements in the feed, comparing each one against the manifest and the file system to verify and download any missing files.
3. **Offline Verification Sync (triggered via `--verify` flag)**
   Runs entirely offline without launching Playwright. It loops through all objects in `downloads/manifest.json`, checks if they exist on disk, adjusts timestamps, and updates comment metadata.
4. **Organization Layout Modes:**
   - **Flat Mode (triggered via `--flat` flag, Default):** Stores files directly under `downloads/[ChildName]/[filename]`.
   - **Nested Mode (triggered via `--nest` flag):** Stores files nested under `downloads/[ChildName]/[YYYY]/[MM]/[filename]`.
   - **Automatic Reorganization:** At startup, check if the download directory exists. If it does, automatically flatten or nest all existing files to match the selected layout mode *before* starting any download sync or verification operation.

### Navigation and Login Flow
1. Launch Playwright's persistent context using `user_data_dir`. To bypass Cloudflare and automation checks:
   - Use `headless = False` by default.
   - Inject argument `"--disable-blink-features=AutomationControlled"`.
   - Ignore default arguments `["--enable-automation"]`.
2. Check login status by going to `https://familyinfocenter.brighthorizons.com/home`.
3. If redirected to a login/auth page, print a warning to the terminal asking the user to manually complete MFA and login in the opened browser window. Poll every second (up to 5 minutes) until the browser URL matches `parents.html` or `dashboard`.
4. Loop through the list of children in `config.json`. For each child, navigate to:
   `https://mybrightday.brighthorizons.com/dashboard/parents.html?dependent_id={dependent_id}`
5. Detect all month/year timeframe links on the right-hand panel (represented by `<li>` elements containing text matching `^[a-z]{3}\s+\d{4}$`).
6. Click timeframe links dynamically. Note that the click handler is bound to the inner `div.tile` child of the `<li>`, so clicking the `<li>` itself does nothing. 
7. After clicking, wait 3 seconds for the feed to reload. Scroll down iteratively to trigger lazy loading of posts. To do this, scroll to the bottom, wait 2.5 seconds, check if the scroll height has increased; if not, do a "shake" scroll (scroll up 600px, wait 500ms, then scroll down again) to ensure lazy-loaded items render.

### Parsing and Downloading Files
1. Inside the feed, find all thumbnail card elements (`ul.thumbnails li` containing `div.tile.pointable`).
2. Extract the source URL from `a.fancybox` (via `href`). 
   - **Video Handling:** If the `href` starts with `#` (local fragment) rather than an attachment URL, it is a video post. Fall back to extracting the URL from the background-image CSS style of the `div.tile.pointable` element (which contains the raw attachment URL parameters).
3. Extract the `obj` parameter from the source URL. Bypassing thumbnail compression: construct the full-resolution download URL as:
   `https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj={obj_id}&key={obj_id}`
4. Check the local `downloads/manifest.json` file. If the `obj_id` is present and the corresponding file exists on disk, handle it according to the selected Sync Mode (skip or stop).
5. Extract the date overlay text (e.g. `6/22` or `06/22/2026`) from `span.name span` inside the card.
   - If not found, parse the card footer text (`.footer.note`) for dates like "Yesterday", "Today", "Month Day, Year", or "Day Month Year".
   - Fall back to the last parsed date in the timeframe, or the start of the timeframe month (`YYYY-MM-01`).
6. Format the date as `YYYY-MM-DD`. Name files as:
   `[ChildName] [YYYY-MM-DD] ([Index]).[extension]`
   (The index increments for multiple items on the same day). Save the files in the directory path corresponding to the active layout mode: `downloads/[ChildName]/` (Flat Mode) or `downloads/[ChildName]/[YYYY]/[MM]/` (Nested Mode).

### File Writing and Metadata Processing
1. Download the file bytes using Playwright's `page.request.get`.
2. Inspect the magic bytes of the downloaded content to determine the correct extension (e.g., `\x89PNG\r\n\x1a\n` for `.png`, `\xff\xd8\xff` for `.jpg`, `ftypmp4` for `.mp4`, or `ftyp` with `qt  ` for `.mov`). Fall back to the response's `content-type` header.
3. Save the file.
4. **Metadata - Write Date Comments:** 
   - If it is a JPEG file, use `piexif` to write the post comment text to `ImageDescription` (0th IFD) and `UserComment` (Exif IFD) tags.
   - If it is a PNG file, write a custom pure-Python injector to insert a standard `tEXt` chunk (keyword: `Description`, value: post comment) immediately following the 33-byte `IHDR` chunk. Calculate the CRC-32 checksum using `zlib.crc32` and write bytes in big-endian format using `struct`.
5. **Metadata - Timestamp:** Convert `10:00 AM` on the post date into a UTC epoch timestamp specifically targeting the `"America/New_York"` timezone (Eastern Time) using Python's `zoneinfo` module. This must handle daylight saving time changes (EST vs. EDT) dynamically. Set the file's modification and access timestamps on disk using `os.utime`.
6. Update and save `downloads/manifest.json` mapping each `obj_id` to its metadata (child, date, year, month, filename, comment).
```
