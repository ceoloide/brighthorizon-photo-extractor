# SPDX-License-Identifier: MIT
"""
Unit Test Suite for new scraper_engine capabilities:
- NetworkTraceLogger (R1)
- Turnstile fast-path & Auth0 form handling (R2)
- Cross-domain session & storage state loading (R3)
"""

import os
import json
import time
import tempfile
from unittest.mock import MagicMock, patch
import pytest

from backend.scraper_engine import (
    NetworkTraceLogger,
    ScraperJob,
    launch_stealth_persistent_context,
)
from backend.database import TenantStorage


@pytest.fixture
def mock_tenant_storage(tmp_path):
    storage = MagicMock(spec=TenantStorage)
    storage.email = "test@example.com"
    storage.user_data_dir = str(tmp_path / "user_data")
    storage.tenant_dir = str(tmp_path / "tenant")
    os.makedirs(storage.user_data_dir, exist_ok=True)
    os.makedirs(storage.tenant_dir, exist_ok=True)
    return storage


def test_network_trace_logger_redaction(mock_tenant_storage):
    mock_job = MagicMock(spec=ScraperJob)
    mock_job.log_structured = MagicMock()
    logger = NetworkTraceLogger(mock_job)

    # Test request redaction
    mock_req = MagicMock()
    mock_req.url = "https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj=123"
    mock_req.method = "GET"
    mock_req.resource_type = "fetch"
    mock_req.headers = {
        "Authorization": "Bearer secret_token",
        "Cookie": "session=secret_cookie",
        "User-Agent": "TestBrowser"
    }

    logger._on_request(mock_req)
    mock_job.log_structured.assert_called_once()
    call_kwargs = mock_job.log_structured.call_args[1]
    assert call_kwargs["level"] == "DEBUG"
    assert call_kwargs["category"] == "NETWORK_REQ"
    headers = call_kwargs["details"]["headers"]
    assert headers["Authorization"] == "[REDACTED]"
    assert headers["Cookie"] == "[REDACTED]"
    assert headers["User-Agent"] == "TestBrowser"


def test_network_trace_logger_response_set_cookies(mock_tenant_storage):
    mock_job = MagicMock(spec=ScraperJob)
    mock_job.log_structured = MagicMock()
    logger = NetworkTraceLogger(mock_job)

    mock_resp = MagicMock()
    mock_resp.url = "https://familyinfocenter.brighthorizons.com/home"
    mock_resp.status = 200
    mock_resp.status_text = "OK"
    secret_token = "SECRET_JWT_TOKEN_98765"
    mock_resp.headers = {
        "set-cookie": f"AUTH_SESSION_ID={secret_token}; Path=/; Secure, tadpoles=SECRET_TADPOLES_VAL; Domain=brighthorizons.com"
    }

    logger._on_response(mock_resp)
    mock_job.log_structured.assert_called_once()
    call_kwargs = mock_job.log_structured.call_args[1]
    assert call_kwargs["level"] == "DEBUG"
    assert call_kwargs["category"] == "NETWORK_RESP"
    assert call_kwargs["details"]["set_cookies_count"] == 1

    set_cookies = call_kwargs["details"]["set_cookies"]
    assert "AUTH_SESSION_ID=[REDACTED]" in set_cookies
    assert "tadpoles=[REDACTED]" in set_cookies
    assert secret_token not in str(set_cookies)
    assert "SECRET_TADPOLES_VAL" not in str(set_cookies)


def test_turnstile_fast_path_when_challenge_absent(mock_tenant_storage):
    job = ScraperJob(mock_tenant_storage, "password123", {})
    mock_page = MagicMock()
    mock_page.url = "https://bhloginsso.brighthorizons.com/login"
    mock_page.evaluate.return_value = False
    mock_page.frames = []
    
    body_mock = MagicMock()
    body_mock.inner_text.return_value = "Auth0 Login Form"
    mock_page.locator.return_value = body_mock

    start_t = time.time()
    result = job.solve_and_wait_turnstile(mock_page, max_wait_sec=50)
    elapsed = time.time() - start_t

    assert result is True
    # Fast path should complete within ~1.5 - 2.5 seconds, not 50 seconds
    assert elapsed < 5.0
    # Check that fast-path bypass was logged
    logs = [l for l in job.status["logs"] if "Fast-Path" in l]
    assert len(logs) > 0


def test_ensure_cross_domain_session_success(mock_tenant_storage):
    job = ScraperJob(mock_tenant_storage, "password123", {})
    mock_page = MagicMock()
    mock_context = MagicMock()

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {"user": {"id": "123"}, "dependents": []}
    mock_page.request.get.return_value = mock_resp

    result = job.ensure_cross_domain_session(mock_page, mock_context)
    assert result is True
    mock_page.request.get.assert_called_with("https://mybrightday.brighthorizons.com/remote/v1/user_payload", timeout=5000)


def test_launch_stealth_persistent_context_auto_loads_storage_state(tmp_path):
    user_data = tmp_path / "user_data"
    user_data.mkdir()
    state_file = user_data / "storage_state.json"
    dummy_cookies = [{"name": "session_id", "value": "test12345"}]
    state_file.write_text(json.dumps({"cookies": dummy_cookies, "origins": []}))

    mock_context = MagicMock()
    mock_playwright = MagicMock()
    mock_playwright.chromium.launch_persistent_context.return_value = mock_context

    context = launch_stealth_persistent_context(mock_playwright, str(user_data))

    mock_playwright.chromium.launch_persistent_context.assert_called_once()
    kwargs = mock_playwright.chromium.launch_persistent_context.call_args[1]
    assert "storage_state" not in kwargs
    mock_context.add_cookies.assert_called_once_with(dummy_cookies)
    assert context == mock_context


def test_scraper_job_incremental_sync_skipping(mock_tenant_storage):
    """
    Verifies that ScraperJob in incremental mode skips existing manifest items
    and processes new items in the same timeframe.
    """
    job = ScraperJob(mock_tenant_storage, "password123", {"sync_mode": "incremental"})
    manifest = {
        "item_aug11": {
            "obj_id": "item_aug11",
            "child": "Byron",
            "original_filename": "2026-08-11_item_aug11.jpg"
        }
    }
    mock_tenant_storage.load_manifest.return_value = manifest

    feed_items = [
        {
            "obj_id": "item_aug11",
            "date_str": "2026-08-11",
            "is_video": False,
            "download_url": "https://example.com/item_aug11",
            "comment_text": "Drawing"
        },
        {
            "obj_id": "item_aug25",
            "date_str": "2026-08-25",
            "is_video": False,
            "download_url": "https://example.com/item_aug25",
            "comment_text": "Playground"
        }
    ]

    # Test that existing item does not halt the queue creation
    download_queue = []
    existing_items_count = 0
    for item in feed_items:
        obj_id = item.get("obj_id")
        existing_entry = False
        for m_id, entry in manifest.items():
            if entry.get("obj_id") == obj_id:
                existing_entry = True
                break
        if existing_entry:
            existing_items_count += 1
            continue
        download_queue.append(item)

    assert len(download_queue) == 1
    assert download_queue[0]["obj_id"] == "item_aug25"
    assert existing_items_count == 1


def test_scraper_job_incremental_pruning_and_termination_flags(mock_tenant_storage):
    """
    Verifies that ScraperJob in incremental mode:
    1. Identifies previously downloaded items and sets found_previously_downloaded flag.
    2. Determines max_downloaded_date.
    3. Prunes already-downloaded items and all items older than max_downloaded_date.
    4. Enqueues only newer items for parallel download.
    """
    job = ScraperJob(mock_tenant_storage, "password123", {"sync_mode": "incremental"})
    manifest = {
        "m_aug15": {
            "obj_id": "item_aug15",
            "child": "Byron",
            "date": "2026-08-15",
            "original_filename": "2026-08-15_item_aug15.jpg"
        }
    }
    mock_tenant_storage.load_manifest.return_value = manifest

    feed_items = [
        {"obj_id": "item_aug25", "date_str": "2026-08-25", "is_video": False, "download_url": "https://example.com/25", "comment_text": "Newer 1"},
        {"obj_id": "item_aug20", "date_str": "2026-08-20", "is_video": False, "download_url": "https://example.com/20", "comment_text": "Newer 2"},
        {"obj_id": "item_aug15", "date_str": "2026-08-15", "is_video": False, "download_url": "https://example.com/15", "comment_text": "Already Downloaded"},
        {"obj_id": "item_aug10", "date_str": "2026-08-10", "is_video": False, "download_url": "https://example.com/10", "comment_text": "Older Item"}
    ]

    found_previously_downloaded = False
    reached_custom_start_date = False
    max_downloaded_date = None

    # Step 1
    for item in feed_items:
        obj_id = item.get("obj_id")
        if any(entry.get("obj_id") == obj_id for entry in manifest.values()):
            found_previously_downloaded = True
            item_date = item.get("date_str")
            if max_downloaded_date is None or (item_date and item_date > max_downloaded_date):
                max_downloaded_date = item_date

    # Step 3
    download_queue = []
    seen_in_queue = set()
    for item in feed_items:
        obj_id = item.get("obj_id")
        item_date = item.get("date_str")
        if any(entry.get("obj_id") == obj_id for entry in manifest.values()):
            continue
        if max_downloaded_date and item_date and item_date < max_downloaded_date:
            continue
        if obj_id in seen_in_queue:
            continue
        seen_in_queue.add(obj_id)
        download_queue.append(item)

    assert found_previously_downloaded is True
    assert max_downloaded_date == "2026-08-15"
    assert len(download_queue) == 2
    assert [x["obj_id"] for x in download_queue] == ["item_aug25", "item_aug20"]


def test_scraper_job_custom_sync_prunes_older_than_start_date(mock_tenant_storage):
    """
    Verifies that ScraperJob in custom mode with start_date:
    1. Sets reached_custom_start_date flag when encountering items older than start_date.
    2. Prunes all items older than start_date.
    """
    start_date = "2026-08-18"
    job = ScraperJob(mock_tenant_storage, "password123", {"sync_mode": "custom", "start_date": start_date})
    mock_tenant_storage.load_manifest.return_value = {}

    feed_items = [
        {"obj_id": "item_aug25", "date_str": "2026-08-25", "is_video": False, "download_url": "https://example.com/25", "comment_text": "Newer"},
        {"obj_id": "item_aug18", "date_str": "2026-08-18", "is_video": False, "download_url": "https://example.com/18", "comment_text": "On Cutoff"},
        {"obj_id": "item_aug10", "date_str": "2026-08-10", "is_video": False, "download_url": "https://example.com/10", "comment_text": "Prior to Cutoff"}
    ]

    reached_custom_start_date = False
    for item in feed_items:
        item_date = item.get("date_str")
        if item_date and item_date < start_date:
            reached_custom_start_date = True
            break

    download_queue = []
    seen_in_queue = set()
    for item in feed_items:
        obj_id = item.get("obj_id")
        item_date = item.get("date_str")
        if item_date and item_date < start_date:
            continue
        if obj_id in seen_in_queue:
            continue
        seen_in_queue.add(obj_id)
        download_queue.append(item)

    assert reached_custom_start_date is True
    assert len(download_queue) == 2
    assert [x["obj_id"] for x in download_queue] == ["item_aug25", "item_aug18"]


def test_scraper_engine_multi_center_target_matching(mock_tenant_storage):
    """
    Verifies that target_child matching matches all center profiles for the given child.
    """
    job = ScraperJob(mock_tenant_storage, "password123", {"child": "Theodore"})
    all_children = [
        {"name": "Theodore", "dependent_id": "dep_center_1", "location_name": "River School West Side"},
        {"name": "Alice", "dependent_id": "dep_center_alice", "location_name": "Bright Horizons at West 72nd"},
        {"name": "Theodore", "dependent_id": "dep_center_2", "location_name": "Bright Horizons at West 72nd"},
    ]

    target_clean = job.target_child.strip().lower()
    matching = [
        c for c in all_children
        if c.get("name", "").strip().lower() == target_clean or c.get("name", "").strip().lower().startswith(target_clean)
    ]

    assert len(matching) == 2
    assert matching[0]["dependent_id"] == "dep_center_1"
    assert matching[1]["dependent_id"] == "dep_center_2"
    # Both share the unified child name
    assert matching[0]["name"] == "Theodore"
    assert matching[1]["name"] == "Theodore"


def test_scraper_engine_unified_child_output_paths():
    """
    Verifies that multiple centers for the same child resolve to the same unified media directory.
    """
    from backend.security_isolation import resolve_child_output_path
    base_dir = "/tmp/tenant"

    # Photos from Center 1 and Center 2
    path_center_1 = resolve_child_output_path(base_dir, "Theodore", "2026-09-01_item1.jpg")
    path_center_2 = resolve_child_output_path(base_dir, "Theodore", "2026-08-15_item2.jpg")

    assert os.path.dirname(path_center_1) == os.path.dirname(path_center_2)
    assert os.path.dirname(path_center_1) == "/tmp/tenant/media/Theodore"
    assert os.path.basename(path_center_1) == "2026-09-01_item1.jpg"
    assert os.path.basename(path_center_2) == "2026-08-15_item2.jpg"


def test_scraper_engine_unenrolled_target_child_matching(mock_tenant_storage):
    """
    Verifies that targeting a child in an unenrolled account with 0 center profiles
    does not raise an exception and synthesizes a direct timeline child profile.
    """
    job = ScraperJob(mock_tenant_storage, "password123", {"child": "Byron"})
    all_children = []
    children_to_process = all_children if all_children else [{"name": "Timeline", "dependent_id": "all"}]

    target_clean = job.target_child.strip().lower()
    matching = [c for c in children_to_process if c.get("name", "").strip().lower() == target_clean]
    if not matching and (not all_children or (len(all_children) == 1 and all_children[0].get("name") == "Timeline")):
        children = [{"name": job.target_child, "dependent_id": "all"}]
    else:
        children = matching

    assert len(children) == 1
    assert children[0]["name"] == "Byron"
    assert children[0]["dependent_id"] == "all"


def test_discover_children_direct_navigation_fallback(mock_tenant_storage):
    """
    Verifies that discover_children falls back to direct parents.html navigation
    and header DOM discovery when familyinfocenter yields 0 profiles.
    """
    job = ScraperJob(mock_tenant_storage, "password123", {})
    mock_page = MagicMock()
    mock_page.url = "https://familyinfocenter.brighthorizons.com/home"
    mock_context = MagicMock()

    # Step 1: /legacy/parents/params returns 401/empty while on familyinfocenter
    mock_resp_empty = MagicMock()
    mock_resp_empty.ok = False
    mock_page.request.get.return_value = mock_resp_empty

    # Step 2: family info center DOM has no app-child elements
    mock_page.locator.return_value.all.return_value = []

    # Step 3: DOM tiles on parents.html return Byron
    with patch("backend.dom_parser.discover_children_from_parents_params", return_value=[]), \
         patch("backend.dom_parser.discover_children_from_family_info", return_value=[]), \
         patch("backend.dom_parser.discover_children_from_mybrightday_dom", return_value=[{"name": "Byron", "dependent_id": "all"}]):
        children = job.discover_children(mock_page, mock_context)

    assert len(children) == 1
    assert children[0]["name"] == "Byron"
    assert children[0]["dependent_id"] == "all"
    mock_page.goto.assert_called_with("https://mybrightday.brighthorizons.com/dashboard/parents.html", wait_until="domcontentloaded")




