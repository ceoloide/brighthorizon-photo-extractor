# SPDX-License-Identifier: MIT
import os
import pytest
from unittest.mock import MagicMock, patch

from backend.database import TenantStorage
from backend.security import get_tenant_id
from backend.scheduler import scan_and_run_scheduled_jobs

def test_tenant_schedule_config_save_load():
    storage = TenantStorage("test_schedule@example.com")
    config = storage.load_config()
    assert config.get("scheduled_incremental") is False

    config["scheduled_incremental"] = True
    storage.save_config(config)

    loaded = storage.load_config()
    assert loaded.get("scheduled_incremental") is True

def test_scan_and_run_scheduled_jobs():
    # Setup tenant 1 (scheduled)
    t1 = TenantStorage("user1@example.com")
    c1 = t1.load_config()
    c1["password"] = "secret1"
    c1["scheduled_incremental"] = True
    t1.save_config(c1)

    # Setup tenant 2 (not scheduled)
    t2 = TenantStorage("user2@example.com")
    c2 = t2.load_config()
    c2["password"] = "secret2"
    c2["scheduled_incremental"] = False
    t2.save_config(c2)

    active_jobs = {}

    with patch("backend.scheduler.ScraperJob") as MockScraperJob:
        mock_job_instance = MagicMock()
        MockScraperJob.return_value = mock_job_instance

        scan_and_run_scheduled_jobs(active_jobs)

        # Should only run for user1
        assert MockScraperJob.call_count == 1
        call_args = MockScraperJob.call_args
        tenant_storage_arg, pwd_arg, options_arg = call_args[0]
        assert tenant_storage_arg.email == "user1@example.com"
        assert pwd_arg == "secret1"
        assert options_arg["sync_mode"] == "incremental"
        assert options_arg["child"] == "all"
        assert mock_job_instance.run.call_count == 1

def test_scan_and_run_scheduled_jobs_skips_running_job():
    t1 = TenantStorage("user1@example.com")
    c1 = t1.load_config()
    c1["password"] = "secret1"
    c1["scheduled_incremental"] = True
    t1.save_config(c1)

    tenant_id1 = get_tenant_id("user1@example.com")
    existing_mock_job = MagicMock()
    existing_mock_job.status = {"state": "running"}
    active_jobs = {tenant_id1: existing_mock_job}

    with patch("backend.scheduler.ScraperJob") as MockScraperJob:
        scan_and_run_scheduled_jobs(active_jobs)
        # MockScraperJob should not be instantiated since tenant 1 has a running job
        assert MockScraperJob.call_count == 0
