# AI Agent Guidelines

This document details critical selector contexts, DOM details, and architectural dependencies of this repository to guide future AI coding agents.

## 1. Playwright Persistent Browser Lock (Singleton Lock)
The scraper uses a persistent browser profile stored in `./user_data/`. 
- **Gotcha:** If you attempt to launch a headful or headless Playwright context using `./user_data` while another instance is already running (e.g. during a background scrape), Chromium will fail with a `TargetClosedError` due to database/singleton locks.
- **Workaround:** For diagnostic or debugging runs in parallel, always copy the user data directory to a copy path, omitting lock files:
  ```bash
  mkdir -p user_data_copy && rsync -a --delete --exclude="Singleton*" --exclude="RunningChromeVersion" --exclude="*Lock*" user_data/ user_data_copy/
  ```
  Then launch your diagnostic script pointing to `./user_data_copy`.

## 2. DOM Selector Subtleties

### A. Timeframe Panel (Months Panel)
- **Timeframe link text match:** `li` elements containing text matching `^[a-z]{3}\s+\d{4}$` (e.g. `jun 2026`).
- **Click target:** The Knockout.js click binding (`click: select`) is attached to the inner `div.tile` child element. **Clicking the parent `<li>` directly does not trigger the feed reload.**
- **HTML structure:**
  ```html
  <li ...>
    <div class="tile pointable" data-bind="click: select">
      ...
    </div>
  </li>
  ```

### B. Kids Selector vs. Feed Thumbnails
- Both the top child selector bar (Byron, Catherine, All Kids) and the feed media listings use the `.thumbnails` class (e.g., `<ul class="thumbnails">`).
- **Gotcha:** Doing `document.querySelectorAll('ul.thumbnails li')` globally will match both the horizontal child filter list at the top and the actual media posts.
- **Fix:** Always scope feed searches inside the timeline's main content well (`div.well.left-panel.pull-left`):
  ```javascript
  const timeline = document.querySelector('div.well.left-panel.pull-left');
  const feedItems = timeline ? timeline.querySelectorAll('ul.thumbnails li') : [];
  ```

### C. Video Posts Link Parsing
- For photo posts, the `a.fancybox` element contains an `href` matching `/remote/v1/obj_attachment?obj=...`.
- For video posts, the `a.fancybox` element has its `href` set to a local DOM fragment indicator (e.g. `href="#6986168d2bb117b0dc910b3b-default"`).
- **Video parsing:** If the scraper sees `a.fancybox`'s `href` starting with `#` or missing `obj_attachment`, it must extract the background image style from `div.tile.pointable`, which contains the actual attachment parameters:
  ```javascript
  const style = tile.getAttribute('style') || '';
  const match = style.match(/url\(['"]?([^'"]+)['"]?\)/);
  if (match) src = match[1]; // matches the obj_attachment endpoint
  ```

## 3. Pure-Python PNG Metadata Injection
To embed text comments into PNG files without introducing heavy external image processing dependencies (like `Pillow`), the codebase uses a custom PNG parser based on standard `zlib` and `struct`.
- **Structure:**
  - Check that the file begins with the PNG magic header (`\x89PNG\r\n\x1a\n`).
  - Search for existing `tEXt` keyword blocks to prevent duplicate writes.
  - Insert a `tEXt` chunk containing key-value metadata (keyword: `Description`, value: post comment) immediately after the first chunk (the `IHDR` chunk, which occupies offsets 8 to 33 in standard PNGs).
  - Ensure the chunk length and CRC checksum (calculated over the type `tEXt` and the text payload) are formatted as big-endian 4-byte integers (`struct.pack('>I', val)`).

## 4. Timezone & DST Calculation
All files must be modified on disk (`os.utime`) to exactly `10:00 AM New York local time` (Eastern Time) using Python's built-in `zoneinfo` module.
- Always use `ZoneInfo("America/New_York")` to convert datetime objects to epoch timestamps, dynamically handling Eastern Standard Time (EST, UTC-5) vs Eastern Daylight Time (EDT, UTC-4) based on the date of the post.
- Avoid using `time.mktime()` directly, as it calculates relative to the host machine's local timezone rather than Eastern Time.
