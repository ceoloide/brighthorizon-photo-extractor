---
name: brighthorizon-extractor
description: Sync, verify, and organize child photo and video downloads from the Bright Horizons parent portal.
---

# Bright Horizons Extractor Skill

Use this skill when you need to sync, download, verify, or organize child media files from the Bright Horizons parent portal.

## Setup Requirements

Before running the extractor, ensure the workspace has:
1. **Playwright Chromium:** Installed via `uv run playwright install chromium`.
2. **Configuration:** A valid `config.json` file in the workspace root matching the following template:
   ```json
   {
     "children": [
       { "name": "Byron", "dependent_id": "INSERT_BYRON_DEPENDENT_ID_HERE" },
       { "name": "Catherine", "dependent_id": "INSERT_CATHERINE_DEPENDENT_ID_HERE" }
     ],
     "user_data_dir": "./user_data",
     "downloads_dir": "./downloads"
   }
   ```

## Available Commands

Always run the scripts using `uv run` to ensure dependencies (like Playwright and Piexif) are automatically resolved without virtual environment management.

### 1. Download Synchronization (Incremental Sync)
Downloads new photos and stops immediately when it encounters the first photo that already exists on disk (highly efficient).
* **Flat Layout (Default):** Saves files directly under `downloads/[Child]/[filename]`
  ```bash
  uv run main.py
  ```
* **Nested Layout:** Saves files nested in subfolders `downloads/[Child]/[YYYY]/[MM]/[filename]`
  ```bash
  uv run main.py --nest
  ```

### 2. Full Sweep Sync
Performs a full sweep of all historical months in the portal to verify and download any missing files:
* **Flat Layout (Default):**
  ```bash
  uv run main.py --full
  ```
* **Nested Layout:**
  ```bash
  uv run main.py --full --nest
  ```

### 3. Offline Verification & Metadata Correction
Verifies all files on disk against the manifest, updates EXIF comments (JPEGs) and `tEXt` Description chunks (PNGs), and corrects timestamps on the filesystem to 10:00 AM New York local time (EST/EDT timezone aware). Runs offline.
* **Flat Layout (Default):**
  ```bash
  uv run main.py --verify
  ```
* **Nested Layout:**
  ```bash
  uv run main.py --verify --nest
  ```

### 4. Layout Reorganization (Offline Utility)
If you need to flat-organize or nest files without running Playwright:
* **Flatten Folders:** `uv run organize_folders.py --flat`
* **Nest Folders:** `uv run organize_folders.py --nest`

## Operational Guidelines & Gotchas

1. **Auto-Reorganization:** When launching `main.py`, the script automatically reorganizes all existing files on disk to match the selected layout mode (`--flat` or `--nest`) *before* checking for duplicates or starting sync.
2. **Login State Interception:** The script runs headful Playwright using a persistent profile (`./user_data`). If a login screen is detected, it will print a clear message asking the user to log in. In agent execution, warn the user first, then launch the sync. Since persistent cookies are saved, re-authentication is only required if the session expires.
3. **Pure-Python PNG Chunk Writing:** Standard EXIF editors do not support PNG files. The script uses a custom chunk editor based on `zlib` and `struct` to write standard `tEXt` chunks. Keep this code intact when modifying metadata handlers.
4. **Eastern Time & DST:** All filesystem timestamps must be exactly `10:00 AM New York local time`. The script handles conversion dynamically based on Eastern Standard Time (EST) vs Eastern Daylight Time (EDT) for each post date.
