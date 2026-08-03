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
    assert call_kwargs["level"] == "INFO"
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
