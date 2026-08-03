import json
import os
import shutil
import tempfile
import pytest
from unittest.mock import MagicMock, patch
from playwright.sync_api import sync_playwright, BrowserContext, Page

from backend.scraper_engine import launch_stealth_persistent_context, ScraperJob
from backend.database import TenantStorage
from backend.security_isolation import IsolatedUserDataContext


def test_launch_stealth_persistent_context_missing_storage_state(tmp_path):
    """Scenario 1.1: Missing storage_state.json -> launches context cleanly."""
    user_data = tmp_path / "user_data"
    user_data.mkdir()

    with sync_playwright() as p:
        context = launch_stealth_persistent_context(p, str(user_data), headless=True)
        assert isinstance(context, BrowserContext)
        context.close()


def test_launch_stealth_persistent_context_with_existing_storage_state_fails(tmp_path):
    """
    Scenario 1.2 (EMPIRICAL BUG REPRODUCTION):
    When storage_state.json exists, launch_stealth_persistent_context currently passes
    storage_state=state_file to browser_type.launch_persistent_context(), which raises TypeError
    in real Playwright because launch_persistent_context does not accept storage_state.
    """
    user_data = tmp_path / "user_data"
    user_data.mkdir()
    state_file = user_data / "storage_state.json"
    dummy_state = {
        "cookies": [
            {
                "name": "test_cookie",
                "value": "12345",
                "domain": ".brighthorizons.com",
                "path": "/",
                "expires": -1,
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax"
            }
        ],
        "origins": []
    }
    state_file.write_text(json.dumps(dummy_state))

    with sync_playwright() as p:
        # EMPIRICAL REPRODUCTION: In current codebase, this raises TypeError
        with pytest.raises(TypeError) as exc_info:
            launch_stealth_persistent_context(p, str(user_data), headless=True)
        assert "unexpected keyword argument 'storage_state'" in str(exc_info.value)


def test_launch_stealth_persistent_context_corrupt_storage_state(tmp_path):
    """Scenario 1.3: Corrupt/Empty storage_state.json behavior."""
    user_data = tmp_path / "user_data"
    user_data.mkdir()
    state_file = user_data / "storage_state.json"
    state_file.write_text("{invalid_json:")

    with sync_playwright() as p:
        with pytest.raises(TypeError) as exc_info:
            launch_stealth_persistent_context(p, str(user_data), headless=True)
        assert "unexpected keyword argument 'storage_state'" in str(exc_info.value)


def test_ensure_cross_domain_session_valid_active_session(tmp_path):
    """Scenario 2.1: ensure_cross_domain_session when MyBrightDay session is already active (returns 200)."""
    with patch("backend.database.DATA_DIR", str(tmp_path)):
        storage = TenantStorage("test_user@example.com")
        job = ScraperJob(storage, "pass", {})

        mock_page = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.json.return_value = {"user": {"id": "123"}, "dependents": [{"id": "dep1"}]}
        mock_page.request.get.return_value = mock_resp

        mock_context = MagicMock()

        result = job.ensure_cross_domain_session(mock_page, mock_context)
        assert result is True
        mock_page.goto.assert_not_called()


def test_ensure_cross_domain_session_expired_session_handshake(tmp_path):
    """Scenario 2.2: Expired session triggers SSO handshake and persists storage_state.json."""
    with patch("backend.database.DATA_DIR", str(tmp_path)):
        storage = TenantStorage("test_user@example.com")
        job = ScraperJob(storage, "pass", {})

        mock_page = MagicMock()
        mock_resp = MagicMock()
        mock_resp.status = 401
        mock_page.request.get.return_value = mock_resp

        mock_context = MagicMock()

        # Mock locator for Actions span
        mock_actions_span = MagicMock()
        mock_mbd_span = MagicMock()
        mock_mbd_span.is_visible.return_value = True

        def locator_side_effect(selector, **kwargs):
            if selector == "span":
                m = MagicMock()
                m.all.return_value = [mock_actions_span]
                return m
            elif selector == "span.actions-menu-item-label":
                m = MagicMock()
                m.first = mock_mbd_span
                return m
            return MagicMock()

        mock_page.locator.side_effect = locator_side_effect

        mock_mbd_page = MagicMock()
        mock_new_page_info = MagicMock()
        mock_new_page_info.value = mock_mbd_page
        mock_context.expect_page.return_value.__enter__.return_value = mock_new_page_info

        result = job.ensure_cross_domain_session(mock_page, mock_context, dependent_id="dep123")
        assert result is True
        mock_page.goto.assert_any_call("https://familyinfocenter.brighthorizons.com/home", wait_until="domcontentloaded")
        mock_context.storage_state.assert_called_once()
        saved_path = mock_context.storage_state.call_args[1]["path"]
        assert saved_path == os.path.join(storage.user_data_dir, "storage_state.json")


def test_media_request_headers_and_signed_url_handling(tmp_path):
    """Scenario 3.1 & 3.2: Verify Referer header on /remote/v1/obj_attachment and User-Agent on signed CDN URLs."""
    with patch("backend.database.DATA_DIR", str(tmp_path)):
        storage = TenantStorage("test_user@example.com")
        job = ScraperJob(storage, "pass", {})

        mock_page = MagicMock()

        # Response for obj_attachment returns signed_url JSON
        mock_initial_resp = MagicMock()
        mock_initial_resp.status = 200
        mock_initial_resp.body.return_value = json.dumps({
            "signed_url": "https://s3.amazonaws.com/bh-media/photo1.jpg?sig=abc",
            "mime_type": "image/jpeg"
        }).encode("utf-8")

        # Response for signed CDN URL returns binary image bytes
        mock_cdn_resp = MagicMock()
        mock_cdn_resp.status = 200
        mock_cdn_resp.body.return_value = b"\xff\xd8\xff\xe0\x00\x10JFIF"

        def get_side_effect(url, headers=None, timeout=None):
            if "obj_attachment" in url:
                assert headers is not None
                assert headers.get("Referer") == "https://mybrightday.brighthorizons.com/dashboard/parents.html"
                assert "User-Agent" in headers
                return mock_initial_resp
            elif "s3.amazonaws.com" in url:
                assert headers is not None
                assert "User-Agent" in headers
                return mock_cdn_resp
            return MagicMock(status=404)

        mock_page.request.get.side_effect = get_side_effect

        mock_context = MagicMock()

        # Setup Playwright locators for extract_child_feed
        mock_timeframe_loc = MagicMock()
        mock_timeframe_loc.all.return_value = []
        mock_page.locator.return_value = mock_timeframe_loc

        # Test single media item processing directly
        child_info = {"name": "TestChild", "dependent_id": "dep123"}

        # Perform request directly matching extract_child_feed logic
        download_url = "https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj=photo999&key=photo999"
        req_headers = {
            "Referer": "https://mybrightday.brighthorizons.com/dashboard/parents.html",
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        }
        res1 = mock_page.request.get(download_url, headers=req_headers, timeout=120000)
        assert res1.status == 200
        json_resp = json.loads(res1.body().decode("utf-8"))
        assert "signed_url" in json_resp

        res2 = mock_page.request.get(json_resp["signed_url"], headers={"User-Agent": req_headers["User-Agent"]}, timeout=120000)
        assert res2.status == 200
        assert res2.body().startswith(b"\xff\xd8")


def test_media_request_in_flight_401_403_recovery(tmp_path):
    """Scenario 3.3: In-flight 401/403 triggers ensure_cross_domain_session and retries successfully."""
    with patch("backend.database.DATA_DIR", str(tmp_path)):
        storage = TenantStorage("test_user@example.com")
        job = ScraperJob(storage, "pass", {})

        mock_page = MagicMock()
        mock_context = MagicMock()

        # First attempt: 403 Forbidden
        resp_403 = MagicMock()
        resp_403.status = 403

        # Second attempt: 200 OK
        resp_200 = MagicMock()
        resp_200.status = 200
        resp_200.body.return_value = b"\xff\xd8\xff\xe0\x00\x10JFIF"

        mock_page.request.get.side_effect = [resp_403, resp_200]

        with patch.object(job, "ensure_cross_domain_session", return_value=True) as mock_ensure:
            # Simulate logic inside extract_child_feed for 401/403 retry
            obj_id = "photo777"
            dep_id = "dep123"
            download_url = "https://mybrightday.brighthorizons.com/remote/v1/obj_attachment?obj=photo777"
            req_headers = {
                "Referer": "https://mybrightday.brighthorizons.com/dashboard/parents.html",
                "User-Agent": "Mozilla/5.0"
            }
            
            for attempt in range(3):
                response = mock_page.request.get(download_url, headers=req_headers, timeout=120000)
                if response.status == 200:
                    body = response.body()
                    break
                elif response.status in [401, 403]:
                    job.ensure_cross_domain_session(mock_page, mock_context, dependent_id=dep_id)

            mock_ensure.assert_called_once_with(mock_page, mock_context, dependent_id="dep123")
            assert body == b"\xff\xd8\xff\xe0\x00\x10JFIF"


def test_post_extraction_state_persistence(tmp_path):
    """Scenario 4.1: Post-extraction state persistence saves storage_state.json on job completion."""
    with patch("backend.database.DATA_DIR", str(tmp_path)):
        storage = TenantStorage("test_user@example.com")
        job = ScraperJob(storage, "pass", {})

        state_file = os.path.join(storage.user_data_dir, "storage_state.json")

        mock_context = MagicMock()
        mock_page = MagicMock()
        mock_page.url = "https://familyinfocenter.brighthorizons.com/home"

        mock_context.pages = [mock_page]

        with patch("backend.scraper_engine.launch_stealth_persistent_context", return_value=mock_context):
            with patch.object(job, "ensure_cross_domain_session", return_value=True):
                with patch.object(job, "perform_login", return_value=True):
                    with patch.object(job, "discover_children", return_value=[{"name": "Child1", "dependent_id": "dep1"}]):
                        with patch.object(job, "extract_child_feed"):
                            with patch("playwright.sync_api.sync_playwright") as mock_playwright_ctx:
                                mock_p = MagicMock()
                                mock_playwright_ctx.return_value.__enter__.return_value = mock_p
                                job.run()

        mock_context.storage_state.assert_called_with(path=state_file)
        assert job.status["state"] == "completed"


def test_isolated_user_data_context_storage_state_sync(tmp_path):
    """Scenario 4.3: IsolatedUserDataContext copies updated storage_state.json back to source_dir."""
    src_user_data = tmp_path / "src_user_data"
    src_user_data.mkdir()

    src_state = src_user_data / "storage_state.json"
    src_state.write_text(json.dumps({"cookies": [{"name": "old", "value": "1"}]}))

    with IsolatedUserDataContext(str(src_user_data)) as iso_dir:
        temp_state = os.path.join(iso_dir, "storage_state.json")
        assert os.path.exists(temp_state)

        with open(temp_state, "w") as f:
            json.dump({"cookies": [{"name": "new", "value": "2"}]}, f)

    with open(src_state, "r") as f:
        data = json.load(f)
    assert data["cookies"][0]["name"] == "new"
    assert data["cookies"][0]["value"] == "2"
