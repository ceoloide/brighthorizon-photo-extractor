# SPDX-License-Identifier: MIT
# Verification Test Script for Job Cancellation Responsiveness & Cleanup
import os
import sys
import time
import pytest
import threading
from unittest.mock import MagicMock, patch

from backend.server import (
    app,
    _active_jobs,
    cancel_extraction,
    start_extraction,
    extraction_status,
    ExtractionRequest,
)
from backend.scraper_engine import ScraperJob
from backend.database import TenantStorage
from backend.security import create_jwt_token, get_tenant_id

TEST_EMAIL = "cancel_audit_test@example.com"
TEST_TENANT_ID = get_tenant_id(TEST_EMAIL)

def setup_function():
    # Clean up _active_jobs and tenant data before each test
    _active_jobs.pop(TEST_TENANT_ID, None)
    storage = TenantStorage(TEST_EMAIL)
    storage.purge_all_data()

def teardown_function():
    _active_jobs.pop(TEST_TENANT_ID, None)
    storage = TenantStorage(TEST_EMAIL)
    storage.purge_all_data()


def test_req1_and_req3_cancel_flag_and_status():
    """Req 1 & 3: Verify POST /api/extraction/cancel sets _cancelled=True and status['state']='cancelled'."""
    storage = TenantStorage(TEST_EMAIL)
    job = ScraperJob(storage, "pass123", {})
    job.status["state"] = "running"
    _active_jobs[TEST_TENANT_ID] = job

    # Call cancellation endpoint function directly
    resp = cancel_extraction(tenant=storage)
    assert resp["status"] == "cancelled"

    # Check job instance flags
    assert job._cancelled is True
    assert job.status["state"] == "cancelled"
    assert "cancelled" in job.status["current_step"].lower()

    # Check extraction_status
    status_resp = extraction_status(tenant=storage)
    assert status_resp["state"] == "cancelled"


def test_req4_lock_release_and_start_after_cancel():
    """Req 4: Verify starting a new extraction after cancellation does not return conflict (409)."""
    storage = TenantStorage(TEST_EMAIL)
    
    # 1. Start first job (mocking job.run)
    with patch.object(ScraperJob, "run", lambda self: time.sleep(0.1)):
        resp1 = start_extraction(ExtractionRequest(sync_mode="incremental"), tenant=storage)
        assert resp1["status"] == "started"
        assert TEST_TENANT_ID in _active_jobs

        # 2. Cancel the job
        resp_cancel = cancel_extraction(tenant=storage)
        assert resp_cancel["status"] == "cancelled"
        assert _active_jobs[TEST_TENANT_ID].status["state"] == "cancelled"

        # 3. Start a second job without force=True
        resp2 = start_extraction(ExtractionRequest(sync_mode="incremental"), tenant=storage)
        assert resp2["status"] == "started"


def test_race_mfa_wait_unblocking():
    """Race Condition 5.2: Test if cancel() unblocks thread waiting on MFA code (_mfa_event)."""
    storage = TenantStorage(TEST_EMAIL)
    job = ScraperJob(storage, "pass123", {})
    
    start_time = time.time()
    def mfa_wait_thread():
        # Simulate thread entering MFA wait step
        job._mfa_event.clear()
        job.status["state"] = "mfa_required"
        got_code = job._mfa_event.wait(timeout=120)
        return got_code

    t = threading.Thread(target=mfa_wait_thread, daemon=True)
    t.start()
    time.sleep(0.2)

    # Invoke cancel
    job.cancel()
    t.join(timeout=3.0)

    elapsed = time.time() - start_time
    is_alive = t.is_alive()
    
    print(f"MFA wait thread alive after cancel(): {is_alive}, elapsed: {elapsed:.2f}s")
    # Audit verdict: If t.is_alive() is True, cancel() failed to unblock MFA event!
    assert not is_alive, f"CRITICAL RETAINED BUG: MFA wait thread remained blocked after job.cancel() (hung for {elapsed:.2f}s)!"


def test_race_manual_step_wait_unblocking():
    """Race Condition 5.3: Test if cancel() unblocks thread waiting on manual step (_step_event)."""
    storage = TenantStorage(TEST_EMAIL)
    job = ScraperJob(storage, "pass123", {"manual_step_mode": True})
    
    start_time = time.time()
    def step_wait_thread():
        job.wait_for_manual_step("Test step", 1)

    t = threading.Thread(target=step_wait_thread, daemon=True)
    t.start()
    time.sleep(0.2)

    # Invoke cancel
    job.cancel()
    t.join(timeout=3.0)

    elapsed = time.time() - start_time
    is_alive = t.is_alive()

    print(f"Manual step wait thread alive after cancel(): {is_alive}, elapsed: {elapsed:.2f}s")
    # Audit verdict: If t.is_alive() is True, cancel() failed to unblock step event!
    assert not is_alive, f"CRITICAL RETAINED BUG: Manual step wait thread remained blocked after job.cancel() (hung for {elapsed:.2f}s)!"


def test_race_item_exception_handling_loop():
    """Race Condition 5.5: Test if context close during item loop causes repeated exception catching log spam."""
    storage = TenantStorage(TEST_EMAIL)
    job = ScraperJob(storage, "pass123", {})
    
    # Mock items and page
    mock_item1 = MagicMock()
    mock_item2 = MagicMock()
    mock_item1.locator.side_effect = Exception("Target page/context closed")
    mock_item2.locator.side_effect = Exception("Target page/context closed")
    
    mock_page = MagicMock()
    mock_timeline = MagicMock()
    mock_timeline.count.return_value = 1
    mock_timeline.locator.return_value.all.return_value = [mock_item1, mock_item2]
    mock_page.locator.return_value = mock_timeline

    mock_tf_li = MagicMock()
    mock_tf_li.inner_text.return_value = "jun 2024"
    mock_tf_tile = MagicMock()
    mock_tf_tile.count.return_value = 1
    mock_tf_li.locator.return_value.first = mock_tf_tile

    mock_page.locator.side_effect = lambda sel, **kwargs: (
        MagicMock(all=lambda: [mock_tf_li]) if sel == "li" else mock_timeline
    )

    # Set cancelled flag
    job._cancelled = True

    # Call extract_child_feed
    job.extract_child_feed(mock_page, MagicMock(), {"name": "Byron", "dependent_id": "123"})

    # Check logs for "Extraction cancelled by user."
    cancelled_logs = [l for l in job.status["logs"] if "Extraction cancelled by user" in l]
    assert len(cancelled_logs) > 0, "extract_child_feed did not log cancellation exit"


def test_req2_playwright_context_close_safety():
    """Req 2: Verify cancel() safely handles missing or already closed _active_page."""
    storage = TenantStorage(TEST_EMAIL)
    job = ScraperJob(storage, "pass123", {})

    # Case 1: _active_page is None
    job._active_page = None
    job.cancel() # Should not raise exception
    assert job._active_page is None

    # Case 2: _active_page context raises exception on close
    mock_page = MagicMock()
    mock_page.context.close.side_effect = Exception("Already closed")
    job._active_page = mock_page
    job.cancel()
    assert job._active_page is None
