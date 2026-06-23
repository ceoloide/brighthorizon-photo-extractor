---
name: brighthorizon-extractor
description: Sync, verify, and organize child photo and video downloads from the Bright Horizons parent portal.
---

# Bright Horizons Extractor Skill

Use this skill when you need to sync, download, verify, or organize child media files from the Bright Horizons parent portal.

## Setup Requirements

Before running the extractor, ensure the workspace has:
1. **Playwright Chromium:** Installed via `uv run playwright install chromium`.
2. **Configuration:** A `config.json` file in the workspace root. Children are **auto-detected** from the portal on first run, so the minimal config is just:
   ```json
   {
     "user_data_dir": "./user_data",
     "downloads_dir": "./downloads"
   }
   ```
   On first run the script will discover each child's name and `dependent_id` from the Bright Horizons dashboard and save them back into `config.json` automatically. Subsequent runs reuse the cached values.

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

## Operational Guidelines & Gotchas

1. **Auto-Detection of Children:** On first run (or when `config.json` has no valid `children` entries), the script navigates to the dashboard and scrapes child names and `dependent_id`s from the child selector bar. Discovered children are persisted to `config.json` so subsequent runs are fast and offline-capable for the children list.
2. **Auto-Reorganization:** When launching `main.py`, the script automatically reorganizes all existing files on disk to match the selected layout mode (`--flat` or `--nest`) *before* checking for duplicates or starting sync.
3. **Login State Interception:** The script runs headful Playwright using a persistent profile (`./user_data`). If a login screen is detected, it will print a clear message asking the user to log in. In agent execution, warn the user first, then launch the sync. Since persistent cookies are saved, re-authentication is only required if the session expires.
4. **Pure-Python PNG Chunk Writing:** Standard EXIF editors do not support PNG files. The script uses a custom chunk editor based on `zlib` and `struct` to write standard `tEXt` chunks. Keep this code intact when modifying metadata handlers.
5. **Eastern Time & DST:** All filesystem timestamps must be exactly `10:00 AM New York local time`. The script handles conversion dynamically based on Eastern Standard Time (EST) vs Eastern Daylight Time (EDT) for each post date.
