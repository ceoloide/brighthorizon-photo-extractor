# SPDX-License-Identifier: MIT
import time
import json
from unittest.mock import MagicMock, patch
import pytest

from backend.scraper_engine import (
    NetworkTraceLogger,
    ScraperJob,
)
from backend.database import TenantStorage


def run_empirical_tests():
    print("=== EMPIRICAL STRESS TEST HARNESS (M12 CHALLENGER) ===")
    
    mock_tenant_storage = MagicMock(spec=TenantStorage)
    mock_tenant_storage.email = "test@example.com"
    mock_tenant_storage.user_data_dir = "/tmp/user_data"
    mock_tenant_storage.tenant_dir = "/tmp/tenant"

    job = ScraperJob(mock_tenant_storage, "password123", {})

    # -------------------------------------------------------------
    # TEST 1: Turnstile Fast-Path Timing when no challenge is present
    # -------------------------------------------------------------
    print("\n--- Test 1.1: Fast-Path Timing (Clean Page) ---")
    mock_page = MagicMock()
    mock_page.url = "https://bhloginsso.brighthorizons.com/login"
    mock_page.evaluate.return_value = False
    mock_page.frames = []
    
    body_mock = MagicMock()
    body_mock.inner_text.return_value = "Auth0 Login Form Email Password"
    mock_page.locator.return_value = body_mock

    start_t = time.time()
    res = job.solve_and_wait_turnstile(mock_page, max_wait_sec=50)
    elapsed = time.time() - start_t
    print(f"Result: {res}, Elapsed: {elapsed:.3f}s")
    assert res is True
    assert 1.4 <= elapsed <= 2.5, f"Expected elapsed ~1.5s, got {elapsed:.3f}s"

    print("--- Test 1.2: Fast-Path Timing when inner_text throws exception ---")
    mock_page_err = MagicMock()
    mock_page_err.url = "https://bhloginsso.brighthorizons.com/login"
    mock_page_err.evaluate.return_value = False
    mock_page_err.frames = []
    body_err = MagicMock()
    body_err.inner_text.side_effect = Exception("DOM node detached")
    mock_page_err.locator.return_value = body_err

    start_t = time.time()
    res_err = job.solve_and_wait_turnstile(mock_page_err, max_wait_sec=50)
    elapsed_err = time.time() - start_t
    print(f"Result: {res_err}, Elapsed: {elapsed_err:.3f}s")
    assert res_err is True
    assert 1.4 <= elapsed_err <= 2.5, f"Expected elapsed ~1.5s, got {elapsed_err:.3f}s"

    # -------------------------------------------------------------
    # TEST 2: Slow Challenge Detection
    # -------------------------------------------------------------
    print("\n--- Test 2.1: Turnstile Challenge Present from Start ---")
    mock_page_cf = MagicMock()
    mock_page_cf.url = "https://bhloginsso.brighthorizons.com/login"
    mock_page_cf.evaluate.return_value = False
    
    cf_frame = MagicMock()
    cf_frame.url = "https://challenges.cloudflare.com/cdn-cgi/challenge-platform/h/g/turnstile/if/ov2/av0/rcv0/0/demo"
    cf_frame.locator("body").inner_text.return_value = "verify you are human"
    mock_page_cf.frames = [cf_frame]
    
    body_mock_cf = MagicMock()
    body_mock_cf.inner_text.return_value = "Verify you are human before proceeding"
    mock_page_cf.locator.return_value = body_mock_cf

    start_t = time.time()
    # Should NOT exit at 1.5s. Will run until max_wait_sec or token populated.
    # We will test max_wait_sec = 3s
    with pytest.raises(Exception, match="Turnstile verification failed"):
        job.solve_and_wait_turnstile(mock_page_cf, max_wait_sec=3)
    elapsed_cf = time.time() - start_t
    print(f"Elapsed with active challenge: {elapsed_cf:.3f}s (Did NOT exit at 1.5s fast-path)")
    assert elapsed_cf >= 3.0

    print("\n--- Test 2.2: Dynamic Challenge Appearance at t=0.8s (within 1.5s grace period) ---")
    start_t = time.time()
    
    def get_frames_dynamic():
        if time.time() - start_t > 0.8:
            return [cf_frame]
        return []

    mock_page_dyn = MagicMock()
    mock_page_dyn.url = "https://bhloginsso.brighthorizons.com/login"
    mock_page_dyn.evaluate.return_value = False
    type(mock_page_dyn).frames = property(lambda self: get_frames_dynamic())
    mock_page_dyn.locator.return_value = body_mock

    with pytest.raises(Exception, match="Turnstile verification failed"):
        job.solve_and_wait_turnstile(mock_page_dyn, max_wait_sec=3)
    elapsed_dyn = time.time() - start_t
    print(f"Elapsed with dynamic challenge at 0.8s: {elapsed_dyn:.3f}s (Cleanly caught and stayed in loop)")
    assert elapsed_dyn >= 3.0

    print("\n--- Test 2.3: Dynamic Challenge Appearance at t=1.8s (AFTER 1.5s grace period) ---")
    start_t = time.time()
    
    def get_frames_late():
        if time.time() - start_t > 1.8:
            return [cf_frame]
        return []

    mock_page_late = MagicMock()
    mock_page_late.url = "https://bhloginsso.brighthorizons.com/login"
    mock_page_late.evaluate.return_value = False
    type(mock_page_late).frames = property(lambda self: get_frames_late())
    mock_page_late.locator.return_value = body_mock

    res_late = job.solve_and_wait_turnstile(mock_page_late, max_wait_sec=5)
    elapsed_late = time.time() - start_t
    print(f"Result for late challenge (1.8s): {res_late}, Elapsed: {elapsed_late:.3f}s")
    if res_late is True and elapsed_late < 1.8:
        print("⚠️ FAILURE MODE DISCOVERED: Fast-Path exited at ~1.5s BEFORE the Turnstile iframe loaded at t=1.8s!")

    # -------------------------------------------------------------
    # TEST 3: Sensitive Header Redaction
    # -------------------------------------------------------------
    print("\n--- Test 3.1: NetworkTraceLogger Request Header Redaction ---")
    mock_job_logger = MagicMock()
    logger = NetworkTraceLogger(mock_job_logger)

    req = MagicMock()
    req.url = "https://bhloginsso.brighthorizons.com/authorize"
    req.method = "POST"
    req.resource_type = "fetch"
    req.headers = {
        "Authorization": "Bearer super_secret_token_123",
        "authorization": "Bearer lower_secret_token_123",
        "Cookie": "session_id=secret_sess_abc",
        "cookie": "user_id=secret_user_def",
        "Set-Cookie": "tracker=secret_track_123",
        "X-Auth-Token": "secret_xauth_999",
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json"
    }

    logger._on_request(req)
    call_args = mock_job_logger.log_structured.call_args[1]
    details = call_args["details"]
    headers = details["headers"]

    print("Redacted Request Headers:")
    for k, v in headers.items():
        print(f"  {k}: {v}")

    assert headers["Authorization"] == "[REDACTED]"
    assert headers["authorization"] == "[REDACTED]"
    assert headers["Cookie"] == "[REDACTED]"
    assert headers["cookie"] == "[REDACTED]"
    assert headers["Set-Cookie"] == "[REDACTED]"
    assert headers["X-Auth-Token"] == "[REDACTED]"
    assert headers["User-Agent"] == "Mozilla/5.0"

    print("\n--- Test 3.2: NetworkTraceLogger Response Set-Cookie Redaction ---")
    mock_job_logger.reset_mock()

    resp = MagicMock()
    resp.url = "https://familyinfocenter.brighthorizons.com/home"
    resp.status = 200
    resp.status_text = "OK"
    resp.headers = {
        "set-cookie": "AUTH_SESSION_ID=SECRET_JWT_TOKEN_VALUE_98765; Path=/; Secure; HttpOnly",
        "Set-Cookie": "TADPOLES_COOKIE=ANOTHER_SECRET_VALUE_54321; Domain=brighthorizons.com"
    }

    logger._on_response(resp)
    call_args_resp = mock_job_logger.log_structured.call_args[1]
    details_resp = call_args_resp["details"]
    
    print("Response Details:")
    print(json.dumps(details_resp, indent=2))

    set_cookies_extracted = details_resp.get("set_cookies", [])
    print(f"set_cookies field in details: {set_cookies_extracted}")

    for sc in set_cookies_extracted:
        if "SECRET_JWT_TOKEN_VALUE_98765" in sc or "ANOTHER_SECRET_VALUE_54321" in sc:
            print("⚠️ SECURITY VULNERABILITY CONFIRMED: Plaintext cookie value leaked in details['set_cookies']!")


if __name__ == "__main__":
    run_empirical_tests()
