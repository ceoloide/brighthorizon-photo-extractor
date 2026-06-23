# Bright Horizon Photo Extractor

This script downloads and organizes children's pictures from the Bright Horizons web portal.

## How it Works
1. **Persistent Browser Session:** It uses Playwright with a persistent browser profile (`./user_data`). This means you only need to log in **once**. The script will automatically remember your session for subsequent runs.
2. **Infinite Scroll Scraper:** It navigates to each child's dashboard, scrolls to load all historical photo posts, and scans the page DOM.
3. **Date Detection:** It extracts the date of each post (e.g. "Today", "June 22, 2026", "22/06/2026") and uses that to name the files: `[ChildName] [YYYY-MM-DD] ([Index]).[extension]`.
4. **Duplicate Prevention:** It maintains a `./downloads/manifest.json` file. Subsequent runs check this manifest and skip downloading photos that have already been retrieved, making sync runs extremely fast.
5. **Metadata Adjustment:** It changes the downloaded image file's modification and access timestamps on your filesystem to 10:00 AM on the day the photo was posted.

---

## Setup Instructions

This project uses the modern, ultra-fast Python package manager **`uv`**. By using `uv`, you do not need to manually install Python, configure virtual environments, or run `pip install`—everything is handled automatically via inline dependency metadata.

### 1. Install `uv`
Open your Terminal and run the installer:

* **macOS / Linux:**
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
  *(Or use Homebrew: `brew install uv`)*

* **Windows:**
  ```powershell
  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```

### 2. Install Playwright Browser Dependencies
Run this single command to download Playwright's Chromium browser dependency:
```bash
uv run playwright install chromium
```

---

## Running the Extractor

You do not need to activate any virtual environment. Simply use `uv run` to execute the script. The script supports two folder layout modes:
* **Flat Mode (`--flat`, Default):** Saves all files directly under `downloads/[ChildName]/[filename]`.
* **Nested Mode (`--nest`):** Saves files in subfolders by year and month: `downloads/[ChildName]/[YYYY]/[MM]/[filename]`.

> [!IMPORTANT]
> **Automatic Reorganization:** If you switch layout modes (e.g., from flat to nested), the script will automatically detect the change and reorganize all existing files on disk to match the selected layout *before* checking for duplicates or starting downloads.

### Sync Modes

1. **Incremental Sync (Default Mode)**
   Optimized for quick daily or weekly updates. It checks the feed from the latest month backwards, stopping as soon as it encounters a photo or video that has already been downloaded:
   * Flat structure (Default):
     ```bash
     uv run main.py
     ```
   * Nested structure:
     ```bash
     uv run main.py --nest
     ```

2. **Full Verification Sync (Verification Mode)**
   Performs a complete sweep of all historical months in the portal, verifying that every photo/video has been downloaded properly and re-downloading any failed files:
   * Flat structure (Default):
     ```bash
     uv run main.py --full
     ```
   * Nested structure:
     ```bash
     uv run main.py --full --nest
     ```

### Post-Processing & Offline Verification
To run an offline check of your downloaded files, set file system timestamps to exactly 10:00 AM New York local time, and inject comments into EXIF (JPEGs) and `tEXt` chunks (PNGs):
* Flat structure (Default):
  ```bash
  uv run main.py --verify
  ```
* Nested structure:
  ```bash
  uv run main.py --verify --nest
  ```

### Initial Run (Login Required)
1. When you run the script for the first time, a Chromium browser window will open.
2. The browser will load the Bright Horizons home page.
3. **Action:** Log in with your credentials. Perform any required multi-factor authentication (MFA/SSO).
4. Once you log in successfully, the script will detect you've logged in, save the session cookies to `./user_data`, and start downloading photos.

### Subsequent Runs
The next time you run `uv run main.py`, the script will reuse the saved session. If your session is still valid, it will scrape, download new photos, and close automatically. *If your session expires in the future, the browser will simply display the login screen again for you to re-authenticate once.*

---

## Output Structure

Based on your selected layout mode:

### Flat Layout (Default)
```text
downloads/
├── manifest.json            # Keeps track of downloaded image IDs to prevent duplicates
├── Child1/
│   ├── Child1 2026-06-22 (1).jpg
│   └── Child1 2026-06-21 (1).jpg
└── Child2/
    ├── Child2 2026-06-22 (1).jpg
    ├── Child2 2026-06-22 (2).jpg  # Handles multiple images on the same day
    └── Child2 2026-06-20 (1).jpg
```

### Nested Layout (`--nest`)
```text
downloads/
├── manifest.json
├── Child1/
│   └── 2026/
│       └── 06/
│           └── Child1 2026-06-22 (1).png
└── Child2/
    └── 2026/
        └── 06/
            ├── Child2 2026-06-22 (1).png
            └── Child2 2026-06-22 (2).png
```
