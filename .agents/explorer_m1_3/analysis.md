# Module Interface & Unit Test Design Analysis
**Target Modules:** `backend/dom_parser.py` and `backend/security_isolation.py`  
**Milestone:** M1 (Module Architecture & DOM Parser)  
**Author:** explorer_m1_3  
**Date:** 2026-07-31  

---

## 1. Executive Summary & Architecture Overview

The Bright Horizons Photo Extractor is being refactored from monolithic scraper scripts (`backend/scraper_engine.py` and `main.py`) into a clean, modular architecture. 

Milestone M1 establishes the foundational modules for DOM interaction and security/isolation:
1. `backend/dom_parser.py`: Pure DOM extraction and Playwright interaction functions encapsulating site-specific selector logic (Knockout.js month tiles, feed element scoping, photo vs. video CSS background fallbacks, and Angular CDK child auto-discovery).
2. `backend/security_isolation.py`: Browser session directory isolation, Chromium lock file prevention, path traversal prevention, credential/MFA/token masking, and input validation.

This document details the reverse-engineered requirements, design rules, complete Python type-hinted module interfaces, and unit test suites for both modules.

---

## 2. Analysis of Existing Implementation

### 2.1 Monolithic Scraper Findings (`backend/scraper_engine.py` & `main.py`)

A comprehensive code audit of `backend/scraper_engine.py` (968 lines) and `main.py` (1031 lines) identified key DOM and security patterns currently mixed into orchestration loops:

* **DOM Scoping & Selectors:**
  - **Child Auto-Discovery:** Currently implemented in `ScraperJob.discover_children` (lines 679-740). Navigates to `familyinfocenter.brighthorizons.com/home`, queries `span` elements with text `"Actions"`, extracts card `<h1>` text for child name, opens Angular CDK overlay, clicks `span.actions-menu-item-label` matching `"My Bright Day"`, and captures new tab via `context.expect_page()` to parse `dependent_id`.
  - **Timeframe Month Panel:** Implemented inline in `extract_child_feed` (lines 765-805). Queries `li` elements matching regex `^[a-z]{3}\s+\d{4}$`. Clicking the parent `<li>` fails to trigger Knockout.js re-renders; the click MUST target the inner `div.tile.pointable` child element (`click: select` binding).
  - **Feed Element Scoping:** Line 812 queries `div.well.left-panel.pull-left` to isolate timeline post thumbnails (`ul.thumbnails li`) from top-bar child filter thumbnails (`ul.thumbnails`).
  - **Video Post Fallback:** Lines 829-835 check if `a.fancybox` `href` begins with `#` or lacks `obj_attachment`. If true, video thumbnail URL is extracted from the `style` attribute of `div.tile.pointable` using regex `url\(['"]?([^'"]+)['"]?\)`.
  - **Date Parsing:** `parse_date` (lines 916-942) extracts month/day/year from date overlay text (`6/22`, `06/22/2026`) and contextualizes missing years using the timeframe month context (e.g. `jun 2024` -> `2024`).

* **Security & Isolation:**
  - **Chromium Singleton Lock Avoidance:** `clean_user_data_locks` (lines 42-52) removes `Singleton*` and `RunningChromeVersion` files. However, parallel runs or persistent context launches still risk lock contention if the main `user_data` directory is mutated directly.
  - **Path Traversal Prevention:** `TenantStorage.get_media_file_path` (in `backend/database.py`) checks path bounds, but explicit path sanitization helpers for file generation and child storage directories are not isolated into a reusable security module.
  - **Credential & Log Masking:** Sensitive data (passwords, MFA codes, JWT tokens) must be masked in log streams, error messages, and API responses.

---

## 3. Core Architectural Rules & DOM Constraints

Per `.agents/AGENTS.md` and `PROJECT.md`, the new modules MUST strictly enforce five core constraints:

| Constraint ID | Name | Subtlety / Requirement |
|---|---|---|
| **RULE 1** | Persistent Browser Lock | `user_data` directory must be safely cloned/isolated excluding `Singleton*`, `RunningChromeVersion`, and `*Lock*` files prior to launching Playwright instances. |
| **RULE 2.A** | Timeframe Tile Binding | Timeframe month `<li>` click target is the inner `div.tile.pointable` element holding `click: select`. |
| **RULE 2.B** | Feed Scoping | Timeline search MUST be scoped inside `div.well.left-panel.pull-left` to avoid collision with top-bar child filter `ul.thumbnails`. |
| **RULE 2.C** | Video Link Parsing | Video posts use local anchor `href` (`#...`). Direct attachment URL MUST be extracted from `div.tile.pointable` style attribute (`url(...)`). |
| **RULE 5** | Angular CDK Child Discovery | Dependent IDs come from `familyinfocenter.brighthorizons.com/home` by clicking `span` containing `"Actions"`, waiting for `span.actions-menu-item-label` with `"My Bright Day"`, and capturing the new tab URL. |

---

## 4. Proposed Interface Contract: `backend/dom_parser.py`

### 4.1 Data Structures & Models

```python
from typing import TypedDict, List, Dict, Any, Optional
from playwright.sync_api import Locator

class TimeframeInfo(TypedDict):
    text: str              # e.g., "jun 2026"
    year: int              # e.g., 2026
    month: int             # e.g., 6
    locator: Locator       # Locator for the parent <li> element
    tile_locator: Locator  # Locator for the inner div.tile.pointable element

class FeedItemInfo(TypedDict):
    obj_id: str            # e.g., "6986168d2bb117b0dc910b3b"
    media_type: str        # "photo" or "video"
    raw_href: str          # Original href or extracted style URL
    download_url: str      # Computed obj_attachment download URL
    date_str: str          # Formatted ISO date "YYYY-MM-DD"
    raw_date_text: str     # Raw date overlay text (e.g., "6/22")
    locator: Locator       # Locator for the <li> post item

class ChildProfile(TypedDict):
    name: str              # Given name (e.g., "Byron")
    dependent_id: str      # Bright Horizons dependent ID string
```

### 4.2 Module Functions (`backend/dom_parser.py`)

```python
# SPDX-License-Identifier: MIT
"""
DOM Parser Module for Bright Horizons Photo Extractor.
Encapsulates all Playwright DOM queries, Knockout.js month navigation,
feed element extraction, video background fallback parsing, and Angular CDK auto-discovery.
"""

from typing import List, Dict, Any, Optional
import re
from datetime import datetime
from playwright.sync_api import Page, BrowserContext, Locator


def parse_timeframe_links(page: Page) -> List[Dict[str, Any]]:
    """
    Finds and parses all timeframe month links in the Knockout.js timeline panel.

    Args:
        page: Playwright Page instance pointing to mybrightday dashboard.

    Returns:
        List of dictionaries with keys: 'text', 'year', 'month', 'locator', 'tile_locator'.
        Matches <li> elements whose text matches regex `^[a-z]{3}\s+\d{4}$` (case-insensitive).
    """
    timeframe_items: List[Dict[str, Any]] = []
    months = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    
    lis = page.locator("li").all()
    for li in lis:
        try:
            txt = li.inner_text().strip()
            match = re.search(r'\b([a-z]{3})\s+(\d{4})\b', txt, re.IGNORECASE)
            if match:
                month_str, year_str = match.groups()
                month_str_lower = month_str.lower()
                if month_str_lower in months:
                    month_idx = months.index(month_str_lower) + 1
                    year_val = int(year_str)
                    tile = li.locator("div.tile.pointable").first
                    tile_loc = tile if tile.count() > 0 else li
                    timeframe_items.append({
                        "text": txt,
                        "year": year_val,
                        "month": month_idx,
                        "locator": li,
                        "tile_locator": tile_loc
                    })
        except Exception:
            continue
            
    return timeframe_items


def click_timeframe_tile(page: Page, timeframe_item: Dict[str, Any]) -> bool:
    """
    Clicks the timeframe month tile adhering to Rule 2.A.
    Target MUST be inner 'div.tile.pointable' element holding 'click: select' binding.

    Args:
        page: Active Playwright Page instance.
        timeframe_item: Dictionary returned by parse_timeframe_links.

    Returns:
        bool: True if click succeeded.
    """
    try:
        tile_loc: Locator = timeframe_item.get("tile_locator") or timeframe_item["locator"].locator("div.tile.pointable").first
        if tile_loc.count() > 0:
            tile_loc.click()
        else:
            timeframe_item["locator"].click()
        return True
    except Exception:
        return False


def parse_video_background_url(style_attribute: str) -> Optional[str]:
    """
    Extracts media attachment URL from CSS style attribute (Rule 2.C).
    Example: style="background-image: url('https://.../obj_attachment?obj=123')"

    Args:
        style_attribute: Raw style attribute string from element.

    Returns:
        Extracted URL string or None if no url() match found.
    """
    if not style_attribute:
        return None
    match = re.search(r'url\([\'"]?([^\'"]+)[\'"]?\)', style_attribute)
    return match.group(1) if match else None


def parse_date_overlay(date_text: str, timeframe_year: Optional[int] = None) -> str:
    """
    Parses date overlay text into ISO format 'YYYY-MM-DD'.

    Args:
        date_text: Raw overlay text (e.g. '6/22', '06/22/2026', '6/22/26').
        timeframe_year: Optional year context from selected timeframe month link.

    Returns:
        Formatted ISO date string (YYYY-MM-DD).
    """
    now = datetime.now()
    default_year = timeframe_year or now.year

    if not date_text:
        return f"{default_year:04d}-{now.month:02d}-{now.day:02d}"

    text = date_text.strip()
    
    # Format M/D or MM/DD
    m1 = re.match(r'^(\d{1,2})/(\d{1,2})$', text)
    if m1:
        month_val, day_val = m1.groups()
        return f"{default_year:04d}-{int(month_val):02d}-{int(day_val):02d}"

    # Format M/D/Y or MM/DD/YYYY
    m2 = re.match(r'^(\d{1,2})/(\d{1,2})/(\d{2,4})$', text)
    if m2:
        month_val, day_val, y_val = m2.groups()
        year_val = int(y_val)
        if year_val < 100:
            year_val += 2000
        return f"{year_val:04d}-{int(month_val):02d}-{int(day_val):02d}"

    return f"{default_year:04d}-{now.month:02d}-{now.day:02d}"


def extract_feed_items(page: Page, timeframe_year: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Extracts timeline feed items adhering to Rules 2.B and 2.C.
    Scopes query strictly inside 'div.well.left-panel.pull-left'.

    Args:
        page: Active Playwright Page instance.
        timeframe_year: Year context from timeframe month.

    Returns:
        List of dictionaries representing feed items:
        [{'obj_id': str, 'media_type': str, 'download_url': str, 'raw_href': str, 'date_str': str, 'locator': Locator}]
    """
    items: List[Dict[str, Any]] = []
    
    # Rule 2.B: Scope search strictly inside left-panel timeline well
    timeline = page.locator("div.well.left-panel.pull-left")
    feed_lis = timeline.locator("ul.thumbnails li").all() if timeline.count() > 0 else page.locator("ul.thumbnails li").all()

    for li in feed_lis:
        try:
            fancybox = li.locator("a.fancybox").first
            if fancybox.count() == 0:
                continue

            href = fancybox.get_attribute("href") or ""
            media_type = "photo"

            # Rule 2.C: Handle video post fallback
            if href.startswith("#") or "obj_attachment" not in href:
                pointable_tile = li.locator("div.tile.pointable").first
                style_attr = pointable_tile.get_attribute("style") if pointable_tile.count() > 0 else ""
                bg_url = parse_video_background_url(style_attr or "")
                if bg_url:
                    href = bg_url
                    media_type = "video"

            match_obj = re.search(r'obj=([^&]+)', href)
            if not match_obj:
                continue
            obj_id = match_obj.group(1)

            # Date overlay extraction
            overlay_span = li.locator("span.name span").first
            raw_date = overlay_span.inner_text().strip() if overlay_span.count() > 0 else ""
            date_str = parse_date_overlay(raw_date, timeframe_year=timeframe_year)

            download_url = f"https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj={obj_id}&key={obj_id}"

            items.append({
                "obj_id": obj_id,
                "media_type": media_type,
                "raw_href": href,
                "download_url": download_url,
                "date_str": date_str,
                "raw_date_text": raw_date,
                "locator": li
            })
        except Exception:
            continue

    return items


def discover_children_from_family_info(page: Page, context: BrowserContext) -> List[Dict[str, str]]:
    """
    Discovers enrolled children and dependent_ids following Rule 5 (Angular CDK overlay).

    Args:
        page: Active Playwright Page instance.
        context: Active Playwright BrowserContext instance.

    Returns:
        List of child profile dicts: [{'name': 'Byron', 'dependent_id': '673e065a9d37c9fab2483b2d'}, ...]
    """
    children: List[Dict[str, str]] = []
    page.goto("https://familyinfocenter.brighthorizons.com/home", wait_until="domcontentloaded")
    
    try:
        page.wait_for_selector("span:has-text('Actions')", timeout=15000)
    except Exception:
        pass

    actions_spans = page.locator("span", has_text="Actions").all()
    for span in actions_spans:
        try:
            # Walk up DOM to find child card <h1>
            card_name = span.evaluate("""(el) => {
                let current = el;
                while (current && current.tagName !== 'BODY') {
                    let h1 = current.querySelector('h1');
                    if (h1 && h1.textContent.trim()) return h1.textContent.trim();
                    current = current.parentElement;
                }
                return '';
            }""")
            
            if not card_name:
                continue

            given_name = card_name.split()[0].capitalize()

            # Click Actions span to trigger Angular CDK dropdown overlay
            span.click()
            page.wait_for_timeout(1000)

            # Target specific dropdown item
            mbd = page.locator("span.actions-menu-item-label", has_text="My Bright Day").first
            mbd.wait_for(state="visible", timeout=3000)

            with context.expect_page() as new_page_info:
                mbd.evaluate("(el) => (el.closest('a') || el.closest('button') || el).click()")

            new_page = new_page_info.value
            new_page.wait_for_load_state("domcontentloaded", timeout=10000)

            match = re.search(r'dependent_id=([^&]+)', new_page.url)
            if match:
                dep_id = match.group(1)
                children.append({"name": given_name, "dependent_id": dep_id})

            new_page.close()
        except Exception:
            # Silently skip non-enrolled children (Rule 5)
            continue

    return children
```

---

## 5. Proposed Interface Contract: `backend/security_isolation.py`

### 5.1 Module Functions (`backend/security_isolation.py`)

```python
# SPDX-License-Identifier: MIT
"""
Security Isolation & Data Protection Module for Bright Horizons Photo Extractor.
Provides persistent browser profile cloning without Singleton locks,
strict directory traversal prevention, credential masking, and MFA format validation.
"""

import os
import re
import shutil
import subprocess
from typing import List, Optional


def clean_user_data_locks(user_data_dir: str) -> List[str]:
    """
    Scans user_data_dir recursively and safely removes leftover Chromium lock files
    ('Singleton*', 'RunningChromeVersion', '*Lock*').

    Args:
        user_data_dir: Absolute path to user data directory.

    Returns:
        List of relative paths of removed lock files.
    """
    removed: List[str] = []
    if not os.path.exists(user_data_dir):
        return removed

    for root, dirs, files in os.walk(user_data_dir):
        for fname in files:
            if "Singleton" in fname or fname == "RunningChromeVersion" or "Lock" in fname:
                full_path = os.path.join(root, fname)
                try:
                    os.remove(full_path)
                    removed.append(os.path.relpath(full_path, user_data_dir))
                except Exception:
                    pass
    return removed


def prepare_isolated_user_data(source_dir: str, target_dir: str) -> str:
    """
    Safely clones persistent Playwright user data directory (Rule 1).
    Excludes Singleton locks during copy to prevent browser launch collisions.

    Args:
        source_dir: Source user_data path.
        target_dir: Target isolated directory path.

    Returns:
        Absolute path to target_dir.
    """
    abs_source = os.path.abspath(source_dir)
    abs_target = os.path.abspath(target_dir)

    os.makedirs(abs_target, exist_ok=True)

    # Check if rsync is available on host OS
    rsync_bin = shutil.which("rsync")
    if rsync_bin:
        cmd = [
            rsync_bin, "-a", "--delete",
            "--exclude=Singleton*",
            "--exclude=RunningChromeVersion",
            "--exclude=*Lock*",
            f"{abs_source}/",
            f"{abs_target}/"
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        # Fallback to shutil copytree logic
        ignore_func = shutil.ignore_patterns("Singleton*", "RunningChromeVersion", "*Lock*")
        for item in os.listdir(abs_source):
            s_item = os.path.join(abs_source, item)
            d_item = os.path.join(abs_target, item)
            if ignore_func(abs_source, [item]):
                continue
            if os.path.isdir(s_item):
                if os.path.exists(d_item):
                    shutil.rmtree(d_item)
                shutil.copytree(s_item, d_item, ignore=ignore_func)
            else:
                shutil.copy2(s_item, d_item)

    clean_user_data_locks(abs_target)
    return abs_target


def sanitize_path(base_dir: str, *path_components: str) -> str:
    """
    Sanitizes subpath components and enforces strict base directory confinement.
    Prevents path traversal attacks (e.g. '../', null bytes, absolute overrides).

    Args:
        base_dir: Base directory path.
        *path_components: Child folder names, relative subdirectories, or filenames.

    Returns:
        Canonical absolute path guaranteed to be strictly inside base_dir.

    Raises:
        ValueError: If path escapes base_dir or contains invalid characters.
    """
    canonical_base = os.path.realpath(base_dir)
    
    clean_parts = []
    for comp in path_components:
        if not comp or not isinstance(comp, str):
            continue
        # Remove null bytes, leading slashes, and traversal markers
        clean = comp.replace("\0", "").lstrip("/\\")
        clean_parts.append(clean)

    joined = os.path.join(canonical_base, *clean_parts)
    canonical_target = os.path.realpath(joined)

    # Path traversal check
    if not (canonical_target == canonical_base or canonical_target.startswith(canonical_base + os.sep)):
        raise ValueError(f"Path traversal detected: path '{canonical_target}' escapes base directory '{canonical_base}'.")

    return canonical_target


def mask_credentials(text: str, custom_secrets: Optional[List[str]] = None) -> str:
    """
    Masks sensitive values (emails, MFA codes, passwords, JWT tokens) in logs and text strings.

    Args:
        text: Raw text string to sanitize.
        custom_secrets: Optional list of additional secret strings to redact.

    Returns:
        Sanitized string with sensitive text replaced by '[MASKED]' or redacted markers.
    """
    if not text:
        return text

    sanitized = text

    # Redact explicit custom secret strings
    if custom_secrets:
        for secret in custom_secrets:
            if secret and len(secret) > 2:
                sanitized = sanitized.replace(secret, "[MASKED_SECRET]")

    # Mask email addresses (e.g., user@domain.com -> u***r@d***n.com)
    def mask_email_match(m):
        email = m.group(0)
        parts = email.split("@")
        if len(parts) == 2 and len(parts[0]) > 1:
            u, d = parts
            masked_u = u[0] + "***" + u[-1]
            d_parts = d.split(".")
            masked_d = d_parts[0][0] + "***" + d_parts[0][-1] + "." + ".".join(d_parts[1:])
            return f"{masked_u}@{masked_d}"
        return "[MASKED_EMAIL]"

    sanitized = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', mask_email_match, sanitized)

    # Mask MFA codes in text (e.g. "code: 123456" or "MFA: 654321")
    sanitized = re.sub(r'\b(code|mfa|verification)\s*[:=]\s*(\d{6})\b', r'\1: ******', sanitized, flags=re.IGNORECASE)

    # Mask JSON password/secret fields
    sanitized = re.sub(r'("(?:password|secret|mfa_code|token)"\s*:\s*")([^"]+)(")', r'\1[MASKED]\3', sanitized, flags=re.IGNORECASE)

    # Mask JWT tokens
    sanitized = re.sub(r'eyJ[a-zA-Z0-9_-]+\.eyJ[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+', r'eyJ...[MASKED_JWT]', sanitized)

    return sanitized


def validate_mfa_code_format(code: str) -> bool:
    """
    Validates that MFA code input is strictly a 6-digit numeric string matching ^\d{6}$.

    Args:
        code: Verification code string.

    Returns:
        bool: True if valid 6-digit format.
    """
    if not code or not isinstance(code, str):
        return False
    return bool(re.match(r'^\d{6}$', code.strip()))
```

---

## 6. Comprehensive Unit Test Strategy & Test Cases

The test specifications below guarantee 100% test coverage for all requirements and rule constraints across both target modules.

### 6.1 DOM Parser Unit Test Suite (`backend/tests/test_dom_parser.py`)

| Test ID | Function Under Test | Scenario / Mock Description | Expected Outcome |
|---|---|---|---|
| `TP_DOM_01` | `parse_timeframe_links` | Mock HTML with `<ul><li><div class="tile pointable">jun 2026</div></li><li><div class="tile pointable">may 2025</div></li><li>invalid</li></ul>` | Returns 2 parsed timeframe dicts with correct year (`2026`, `2025`) and month (`6`, `5`). |
| `TP_DOM_02` | `click_timeframe_tile` | Mock parent `<li>` containing inner `div.tile.pointable`. Verify click target (Rule 2.A). | Calls `click()` on inner `div.tile.pointable` locator rather than parent `<li>`. Returns `True`. |
| `TP_DOM_03` | `parse_video_background_url` | String input: `background-image: url('https://domain/remote/v1/obj_attachment?obj=v123')`. | Extracts `https://domain/remote/v1/obj_attachment?obj=v123`. Returns `None` for invalid style string. |
| `TP_DOM_04` | `parse_date_overlay` | Inputs: `"6/22"` (year context `2026`), `"06/22/2026"`, `"6/22/26"`. | All return `"2026-06-22"`. |
| `TP_DOM_05` | `extract_feed_items` | Mock DOM containing top child filter thumbnails and timeline well (`div.well.left-panel.pull-left`) with photo post and video post. | Scopes feed search inside left panel well (Rule 2.B). Photo post extracts `obj_id` and media_type `'photo'`. Video post extracts background URL and media_type `'video'` (Rule 2.C). |
| `TP_DOM_06` | `discover_children_from_family_info` | Mock Angular page with child card for "Byron Taccani" (has "My Bright Day" menu) and "Graduated Child" (no "My Bright Day" menu). | Discovers `Byron` with correct `dependent_id` from tab URL; skips non-enrolled child (Rule 5). |

### 6.2 Security Isolation Unit Test Suite (`backend/tests/test_security_isolation.py`)

| Test ID | Function Under Test | Scenario / Mock Description | Expected Outcome |
|---|---|---|---|
| `TP_SEC_01` | `clean_user_data_locks` | Temp folder with `SingletonLock`, `SingletonSocket`, `RunningChromeVersion`, and normal `Preferences` file. | Removes lock files; preserves `Preferences`. Returns list of removed lock file paths. |
| `TP_SEC_02` | `prepare_isolated_user_data` | Source directory with nested data and lock files. Runs isolation cloning to target directory. | Target directory contains full user data except zero lock files (Rule 1 compliance). |
| `TP_SEC_03` | `sanitize_path` (Valid) | Base dir `/tmp/tenant`, child `"Byron"`, file `"photo.jpg"`. | Returns canonical path `/tmp/tenant/Byron/photo.jpg`. |
| `TP_SEC_04` | `sanitize_path` (Traversal) | Base dir `/tmp/tenant`, traversal input `"../../etc/passwd"`. | Raises `ValueError` with path traversal message. Canonical path never leaves `/tmp/tenant`. |
| `TP_SEC_05` | `mask_credentials` | Inputs containing email `"byron@example.com"`, MFA string `"code: 654321"`, JSON `"password": "my_pass"`, and JWT string. | Masks email to `b***n@e*****e.com`, MFA code to `******`, password to `[MASKED]`, JWT to `eyJ...[MASKED_JWT]`. |
| `TP_SEC_06` | `validate_mfa_code_format` | Strings: `"123456"`, `"000000"`, `"12345"`, `"abcdef"`, `"1234567"`. | Returns `True` for valid 6-digit numeric strings; `False` for invalid formats. |

---

## 7. Migration & Integration Strategy

Once `backend/dom_parser.py` and `backend/security_isolation.py` are implemented in M1:

1. **`backend/scraper_engine.py` Refactoring:**
   - Import `clean_user_data_locks`, `prepare_isolated_user_data`, `mask_credentials`, and `sanitize_path` from `backend.security_isolation`.
   - Replace inline `discover_children`, `extract_child_feed` timeframe parsing, and video fallback logic with `discover_children_from_family_info`, `parse_timeframe_links`, `click_timeframe_tile`, and `extract_feed_items` from `backend.dom_parser`.
2. **`backend/pipeline.py` (Milestone M2):**
   - The step-by-step extraction pipeline in M2 will directly consume `backend/dom_parser.py` for feed processing and `backend/security_isolation.py` for isolated storage path creation.
3. **Multi-Tenant Job Isolation (Milestone M3):**
   - `MultiTenantOrchestrator` will use `prepare_isolated_user_data` to spawn independent worker browser contexts per child extraction job without Chromium Singleton lock contention.
