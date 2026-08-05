# SPDX-License-Identifier: MIT
"""
Unit Test Suite for backend/multi_tenant.py.

Tests ExtractionJob data structure, MultiTenantOrchestrator job management,
child auto-discovery integration, profile lock isolation, error masking,
cancellation, multi-child execution, and master manifest consolidation.
"""

import os
import json
import tempfile
from unittest.mock import MagicMock, patch, ANY

import pytest

from backend import security_isolation
from backend.multi_tenant import ExtractionJob, MultiTenantOrchestrator


# =============================================================================
# Category 1: ExtractionJob Model and State Transition Tests
# =============================================================================

def test_extraction_job_initialization():
    job = ExtractionJob(
        job_id="job_123",
        tenant_id="tenant_abc",
        child_name="Byron",
        dependent_id="dep123",
        user_data_dir="/tmp/user_data",
        output_dir="/tmp/output",
        start_date="2026-01-01",
        sync_mode="incremental",
    )

    assert job.job_id == "job_123"
    assert job.tenant_id == "tenant_abc"
    assert job.child_name == "Byron"
    assert job.dependent_id == "dep123"
    assert job.status == "pending"
    assert job.created_at is not None
    assert job.completed_at is None
    assert job.result is None
    assert job.error is None


def test_extraction_job_status_updates():
    job = ExtractionJob(
        job_id="job_456",
        tenant_id="default_tenant",
        child_name="Catherine",
        dependent_id="dep456",
        user_data_dir="/tmp/user_data",
        output_dir="/tmp/output",
    )

    job.status = "running"
    assert job.status == "running"

    job.status = "completed"
    job.completed_at = "2026-07-31T10:00:00"
    job.result = {"downloaded_count": 5}
    assert job.status == "completed"
    assert job.result["downloaded_count"] == 5

    job.status = "failed"
    job.error = "Unauthenticated session"
    assert job.status == "failed"
    assert job.error == "Unauthenticated session"


# =============================================================================
# Category 2: Orchestrator Job Enqueueing & Sanitization Tests
# =============================================================================

def test_create_and_submit_job(tmp_path):
    user_data = str(tmp_path / "user_data")
    output_dir = str(tmp_path / "downloads")

    orchestrator = MultiTenantOrchestrator(
        base_user_data_dir=user_data,
        base_output_dir=output_dir,
    )

    job1 = orchestrator.submit_job(
        child_name="Byron",
        dependent_id="dep_byron",
        start_date="2026-06-01",
        sync_mode="full",
    )

    assert job1.job_id in orchestrator.jobs
    assert job1.child_name == "Byron"
    assert job1.dependent_id == "dep_byron"
    assert job1.start_date == "2026-06-01"
    assert job1.sync_mode == "full"
    assert job1.status == "pending"


def test_create_job_adversarial_child_name(tmp_path):
    orchestrator = MultiTenantOrchestrator(
        base_user_data_dir=str(tmp_path / "user_data"),
        base_output_dir=str(tmp_path / "output"),
    )

    # Path traversal attempt in child name
    job = orchestrator.create_job(
        child_name="../../etc/passwd/Byron",
        dependent_id="dep999",
    )

    # Name should be sanitized to safe folder name
    assert ".." not in job.child_name
    assert "/" not in job.child_name
    assert "\\" not in job.child_name
    assert job.child_name == "Etcpasswdbyron"


def test_tenant_storage_concurrent_manifest_writes(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from backend.database import TenantStorage

    storage = TenantStorage(email="test_concurrent@example.com")
    
    def _write_media(i):
        obj_id = f"obj_{i:03d}"
        storage.add_media_entry(
            obj_id=obj_id,
            child="Byron",
            date_str="2026-06-15",
            original_filename=f"Byron 2026-06-15 ({i:02d}).jpg",
            comment="Test photo",
            file_bytes=b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01",
            mime_type="image/jpeg"
        )

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(_write_media, i) for i in range(20)]
        for f in futures:
            f.result()

    manifest = storage.load_manifest()
    assert len(manifest) == 20
    obj_ids = {entry["obj_id"] for entry in manifest.values()}
    assert len(obj_ids) == 20


# =============================================================================
# Category 3: Auto-Discovery Integration Tests
# =============================================================================

def test_discover_children_success(tmp_path):
    orchestrator = MultiTenantOrchestrator(
        base_user_data_dir=str(tmp_path / "user_data"),
        base_output_dir=str(tmp_path / "output"),
    )

    mock_pw = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()
    mock_context.pages = [mock_page]
    mock_pw.chromium.launch_persistent_context.return_value = mock_context

    mock_children = [
        {"name": "Byron", "given_name": "Byron", "full_name": "Byron Massarelli", "dependent_id": "dep_byron"},
        {"name": "Catherine", "given_name": "Catherine", "full_name": "Catherine Massarelli", "dependent_id": "dep_cath"},
    ]

    with patch("backend.dom_parser.discover_children_from_family_info", return_value=mock_children):
        discovered = orchestrator.discover_children(playwright_instance=mock_pw)

    assert len(discovered) == 2
    assert discovered[0]["name"] == "Byron"
    assert discovered[1]["name"] == "Catherine"
    mock_pw.chromium.launch_persistent_context.assert_called_once()


def test_discover_children_fallback_empty(tmp_path):
    orchestrator = MultiTenantOrchestrator(
        base_user_data_dir=str(tmp_path / "user_data"),
        base_output_dir=str(tmp_path / "output"),
    )

    mock_pw = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()
    mock_context.pages = [mock_page]
    mock_pw.chromium.launch_persistent_context.return_value = mock_context

    with patch("backend.dom_parser.discover_children_from_family_info", return_value=[]):
        discovered = orchestrator.discover_children(playwright_instance=mock_pw)

    assert discovered == []


# =============================================================================
# Category 4: Single Job Execution & Error/Cancellation Tests
# =============================================================================

def test_run_job_success(tmp_path):
    output_dir = str(tmp_path / "downloads")
    orchestrator = MultiTenantOrchestrator(
        base_user_data_dir=str(tmp_path / "user_data"),
        base_output_dir=output_dir,
    )

    job = orchestrator.create_job(
        child_name="Byron",
        dependent_id="dep123",
    )

    mock_pw = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()
    mock_context.pages = [mock_page]
    mock_pw.chromium.launch_persistent_context.return_value = mock_context

    pipeline_result = {
        "status": "completed",
        "child_name": "Byron",
        "dependent_id": "dep123",
        "processed_count": 2,
        "downloaded_count": 2,
        "skipped_count": 0,
        "manifest": {"img1": {"obj_id": "img1", "child": "Byron"}},
    }

    with patch("backend.pipeline.run_extraction_pipeline", return_value=pipeline_result):
        res = orchestrator.run_job(job, playwright_instance=mock_pw)

    assert res["status"] == "completed"
    assert job.status == "completed"
    assert job.result["downloaded_count"] == 2
    assert job.completed_at is not None


def test_run_job_pipeline_error_masking(tmp_path):
    orchestrator = MultiTenantOrchestrator(
        base_user_data_dir=str(tmp_path / "user_data"),
        base_output_dir=str(tmp_path / "downloads"),
    )

    job = orchestrator.create_job(
        child_name="Byron",
        dependent_id="dep123",
    )

    mock_pw = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()
    mock_context.pages = [mock_page]
    mock_pw.chromium.launch_persistent_context.return_value = mock_context

    # Error containing sensitive password and MFA token
    raw_error = "Unauthenticated session: password=Secret123 & mfa_code: 123456"

    with patch("backend.pipeline.run_extraction_pipeline", side_effect=RuntimeError(raw_error)):
        res = orchestrator.run_job(job, playwright_instance=mock_pw)

    assert res["status"] == "failed"
    assert job.status == "failed"

    # Verify sensitive data was redacted in job.error
    assert "Secret123" not in job.error
    assert "123456" not in job.error
    assert "***REDACTED_PASSWORD***" in job.error


def test_run_job_cancellation_before_execution(tmp_path):
    orchestrator = MultiTenantOrchestrator(
        base_user_data_dir=str(tmp_path / "user_data"),
        base_output_dir=str(tmp_path / "downloads"),
    )

    job = orchestrator.create_job(child_name="Byron", dependent_id="dep123")
    orchestrator.cancel_job(job.job_id)

    mock_pw = MagicMock()
    res = orchestrator.run_job(job.job_id, playwright_instance=mock_pw)

    assert res["status"] == "cancelled"
    assert job.status == "cancelled"
    mock_pw.chromium.launch_persistent_context.assert_not_called()


def test_run_job_cancellation_during_execution(tmp_path):
    orchestrator = MultiTenantOrchestrator(
        base_user_data_dir=str(tmp_path / "user_data"),
        base_output_dir=str(tmp_path / "downloads"),
    )

    job = orchestrator.create_job(child_name="Byron", dependent_id="dep123")

    mock_pw = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()
    mock_context.pages = [mock_page]
    mock_pw.chromium.launch_persistent_context.return_value = mock_context

    pipeline_cancelled = {
        "status": "cancelled",
        "child_name": "Byron",
        "downloaded_count": 0,
    }

    with patch("backend.pipeline.run_extraction_pipeline", return_value=pipeline_cancelled):
        res = orchestrator.run_job(
            job,
            playwright_instance=mock_pw,
            cancel_checker=lambda: True,
        )

    assert res["status"] == "cancelled"
    assert job.status == "cancelled"


# =============================================================================
# Category 5: Multi-Child & Orchestration Integration Tests
# =============================================================================

def test_run_all_jobs_aggregate_summary(tmp_path):
    output_dir = str(tmp_path / "downloads")
    orchestrator = MultiTenantOrchestrator(
        base_user_data_dir=str(tmp_path / "user_data"),
        base_output_dir=output_dir,
    )

    job1 = orchestrator.create_job("Byron", "dep1")
    job2 = orchestrator.create_job("Catherine", "dep2")

    mock_pw = MagicMock()
    mock_context = MagicMock()
    mock_page = MagicMock()
    mock_context.pages = [mock_page]
    mock_pw.chromium.launch_persistent_context.return_value = mock_context

    def mock_pipeline(page, child_name, **kwargs):
        return {
            "status": "completed",
            "child_name": child_name,
            "downloaded_count": 3 if child_name == "Byron" else 2,
            "skipped_count": 1,
            "manifest": {f"item_{child_name}": {"obj_id": f"item_{child_name}"}},
        }

    with patch("backend.pipeline.run_extraction_pipeline", side_effect=mock_pipeline):
        summary = orchestrator.run_all_jobs(playwright_instance=mock_pw)

    assert summary["total_jobs"] == 2
    assert summary["succeeded"] == 2
    assert summary["failed"] == 0
    assert summary["total_downloaded"] == 5
    assert summary["total_skipped"] == 2
    assert os.path.exists(summary["master_manifest_path"])


def test_run_all_children(tmp_path):
    orchestrator = MultiTenantOrchestrator(
        base_user_data_dir=str(tmp_path / "user_data"),
        base_output_dir=str(tmp_path / "output"),
    )

    mock_pw = MagicMock()

    mock_children = [
        {"name": "Byron", "dependent_id": "dep1"},
        {"name": "Catherine", "dependent_id": "dep2"},
    ]

    with patch.object(orchestrator, "discover_children", return_value=mock_children), \
         patch.object(orchestrator, "run_all_jobs", return_value={"total_jobs": 2, "succeeded": 2}) as mock_run_all:

        summary = orchestrator.run_all_children(playwright_instance=mock_pw)

    assert len(orchestrator.jobs) == 2
    mock_run_all.assert_called_once()
    assert summary["total_jobs"] == 2


def test_orchestrate_extraction_filtered_target(tmp_path):
    orchestrator = MultiTenantOrchestrator(
        base_user_data_dir=str(tmp_path / "user_data"),
        base_output_dir=str(tmp_path / "output"),
    )

    mock_pw = MagicMock()
    mock_children = [
        {"name": "Byron", "full_name": "Byron Massarelli", "dependent_id": "dep1"},
        {"name": "Catherine", "full_name": "Catherine Massarelli", "dependent_id": "dep2"},
    ]

    with patch.object(orchestrator, "discover_children", return_value=mock_children), \
         patch.object(orchestrator, "run_all_jobs", return_value={"total_jobs": 1, "succeeded": 1}):

        orchestrator.orchestrate_extraction(target_child="Byron", playwright_instance=mock_pw)

    assert len(orchestrator.jobs) == 1
    assert list(orchestrator.jobs.values())[0].child_name == "Byron"


def test_orchestrate_extraction_fallback_target(tmp_path):
    orchestrator = MultiTenantOrchestrator(
        base_user_data_dir=str(tmp_path / "user_data"),
        base_output_dir=str(tmp_path / "output"),
    )

    mock_pw = MagicMock()

    # Auto-discovery returns empty list
    with patch.object(orchestrator, "discover_children", return_value=[]), \
         patch.object(orchestrator, "run_all_jobs", return_value={"total_jobs": 1, "succeeded": 1}):

        orchestrator.orchestrate_extraction(target_child="Byron", playwright_instance=mock_pw)

    # Should create fallback job for Byron
    assert len(orchestrator.jobs) == 1
    assert list(orchestrator.jobs.values())[0].child_name == "Byron"


# =============================================================================
# Category 6: Master Manifest Consolidation & Profile Isolation Tests
# =============================================================================

def test_master_manifest_consolidation(tmp_path):
    output_dir = tmp_path / "output"
    byron_dir = output_dir / "media" / "Byron"
    catherine_dir = output_dir / "media" / "Catherine"

    byron_dir.mkdir(parents=True)
    catherine_dir.mkdir(parents=True)

    byron_manifest = {"item1": {"obj_id": "item1", "child": "Byron"}}
    catherine_manifest = {"item2": {"obj_id": "item2", "child": "Catherine"}}

    (byron_dir / "manifest.json").write_text(json.dumps(byron_manifest))
    (catherine_dir / "manifest.json").write_text(json.dumps(catherine_manifest))

    orchestrator = MultiTenantOrchestrator(base_output_dir=str(output_dir))
    orchestrator._consolidate_master_manifest(str(output_dir))

    master_file = output_dir / "manifest.json"
    assert master_file.exists()

    master_data = json.loads(master_file.read_text())
    assert "item1" in master_data
    assert "item2" in master_data
    assert master_data["item1"]["child"] == "Byron"
    assert master_data["item2"]["child"] == "Catherine"
