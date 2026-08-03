# SPDX-License-Identifier: MIT
"""
Multi-Tenant & Multi-Child Extraction Orchestrator Module for Bright Horizons Photo Extractor.

Manages isolated extraction jobs across multiple child profiles and parent accounts
without Chromium lock collisions using IsolatedUserDataContext, dom_parser, and pipeline.
Spec reference: .agents/explorer_m3/analysis.md
"""

import os
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable, Union

from playwright.sync_api import sync_playwright

from backend import dom_parser
from backend import pipeline
from backend import security_isolation


@dataclass
class ExtractionJob:
    job_id: str
    tenant_id: str
    child_name: str
    dependent_id: str
    user_data_dir: str
    output_dir: str
    start_date: Optional[str] = None
    sync_mode: str = "incremental"  # "incremental" | "full"
    status: str = "pending"  # "pending" | "running" | "completed" | "failed" | "cancelled"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    completed_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class MultiTenantOrchestrator:
    """
    Coordinates multi-child and multi-tenant extraction workflows with profile lock isolation,
    job queue state tracking, child auto-discovery, and master manifest consolidation.
    """

    def __init__(
        self,
        base_user_data_dir: str = "./user_data",
        base_output_dir: str = "./data",
        max_concurrent_jobs: int = 1,
        sync_back_state: bool = True,
        logger: Optional[Callable[[str], None]] = None,
    ):
        self.base_user_data_dir = os.path.abspath(base_user_data_dir)
        self.base_output_dir = os.path.abspath(base_output_dir)
        self.max_concurrent_jobs = max_concurrent_jobs
        self.sync_back_state = sync_back_state
        self.sanitized_logger = security_isolation.SanitizedLogger(logger or print)
        self.logger = self.sanitized_logger.log
        self.jobs: Dict[str, ExtractionJob] = {}
        self.cancelled_job_ids: set = set()

    def discover_children(
        self,
        user_data_dir: Optional[str] = None,
        playwright_instance: Optional[Any] = None,
        headless: bool = True,
    ) -> List[Dict[str, str]]:
        """
        Auto-discovers active children from the portal using IsolatedUserDataContext
        and dom_parser.discover_children_from_family_info.
        """
        src_user_data = os.path.abspath(user_data_dir or self.base_user_data_dir)
        self.logger(f"Starting child auto-discovery using user_data_dir: {src_user_data}")

        children: List[Dict[str, str]] = []

        with security_isolation.IsolatedUserDataContext(src_user_data, sync_back_state=False) as iso_dir:
            def _discover_with_pw(pw):
                context = pw.chromium.launch_persistent_context(
                    user_data_dir=iso_dir,
                    headless=headless,
                )
                try:
                    page = context.pages[0] if context.pages else context.new_page()
                    return dom_parser.discover_children_from_family_info(page, context, logger=self.logger)
                finally:
                    try:
                        context.close()
                    except Exception:
                        pass

            if playwright_instance is not None:
                children = _discover_with_pw(playwright_instance)
            else:
                with sync_playwright() as pw:
                    children = _discover_with_pw(pw)

        self.logger(f"Discovered {len(children)} active child profile(s).")
        return children

    def submit_job(
        self,
        child_name: str,
        dependent_id: str,
        user_data_dir: Optional[str] = None,
        output_dir: Optional[str] = None,
        start_date: Optional[str] = None,
        sync_mode: str = "incremental",
        tenant_id: str = "default_tenant",
    ) -> ExtractionJob:
        """Creates and enqueues an extraction job."""
        return self.create_job(
            child_name=child_name,
            dependent_id=dependent_id,
            user_data_dir=user_data_dir,
            output_dir=output_dir,
            start_date=start_date,
            sync_mode=sync_mode,
            tenant_id=tenant_id,
        )

    def create_job(
        self,
        child_name: str,
        dependent_id: str,
        user_data_dir: Optional[str] = None,
        output_dir: Optional[str] = None,
        start_date: Optional[str] = None,
        sync_mode: str = "incremental",
        tenant_id: str = "default_tenant",
    ) -> ExtractionJob:
        """
        Instantiates an ExtractionJob with status 'pending', sanitizes child name, and records job.
        """
        job_id = f"job_{uuid.uuid4().hex[:12]}"
        clean_child = security_isolation.sanitize_child_name(child_name)
        resolved_output = os.path.abspath(output_dir or self.base_output_dir)
        resolved_user_data = os.path.abspath(user_data_dir or self.base_user_data_dir)

        job = ExtractionJob(
            job_id=job_id,
            tenant_id=tenant_id,
            child_name=clean_child,
            dependent_id=dependent_id,
            user_data_dir=resolved_user_data,
            output_dir=resolved_output,
            start_date=start_date,
            sync_mode=sync_mode,
            status="pending",
        )

        self.jobs[job_id] = job
        self.logger(f"Enqueued job {job_id} for child '{clean_child}' (dependent_id: {dependent_id})")
        return job

    def cancel_job(self, job_id: str) -> bool:
        """
        Cancels an enqueued or running job by job_id.
        """
        self.cancelled_job_ids.add(job_id)
        if job_id in self.jobs:
            job = self.jobs[job_id]
            job.status = "cancelled"
            job.error = "Job cancelled by user request"
            self.logger(f"Job {job_id} set to cancelled.")
            return True
        return False

    def is_job_cancelled(self, job_id: str) -> bool:
        return job_id in self.cancelled_job_ids or (
            job_id in self.jobs and self.jobs[job_id].status == "cancelled"
        )

    def run_job(
        self,
        job_id_or_job: Union[str, ExtractionJob],
        playwright_instance: Optional[Any] = None,
        headless: bool = True,
        cancel_checker: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """
        Executes an extraction job using IsolatedUserDataContext and pipeline.run_extraction_pipeline.
        Updates job status to running/completed/failed/cancelled, records metrics, and updates master manifest.
        """
        if isinstance(job_id_or_job, str):
            job_id = job_id_or_job
            job = self.jobs.get(job_id)
            if not job:
                raise KeyError(f"Job {job_id} not found in orchestrator jobs.")
        else:
            job = job_id_or_job
            job_id = job.job_id
            if job_id not in self.jobs:
                self.jobs[job_id] = job

        if self.is_job_cancelled(job_id):
            job.status = "cancelled"
            job.error = "Job cancelled before execution"
            self.logger(f"Skipping cancelled job {job_id}")
            return {"status": "cancelled", "job_id": job_id, "child_name": job.child_name}

        job.status = "running"
        self.logger(f"Running extraction job {job_id} for '{job.child_name}'...")

        def _combined_cancel_checker() -> bool:
            if cancel_checker and cancel_checker():
                return True
            return self.is_job_cancelled(job_id)

        try:
            with security_isolation.IsolatedUserDataContext(
                job.user_data_dir, sync_back_state=self.sync_back_state
            ) as iso_user_data:
                def _execute_pipeline(pw):
                    context = pw.chromium.launch_persistent_context(
                        user_data_dir=iso_user_data,
                        headless=headless,
                    )
                    try:
                        page = context.pages[0] if context.pages else context.new_page()
                        return pipeline.run_extraction_pipeline(
                            page=page,
                            child_name=job.child_name,
                            dependent_id=job.dependent_id,
                            output_dir=job.output_dir,
                            start_date=job.start_date,
                            sync_mode=job.sync_mode,
                            cancel_checker=_combined_cancel_checker,
                            logger=self.logger,
                        )
                    finally:
                        try:
                            context.close()
                        except Exception:
                            pass

                if playwright_instance is not None:
                    res = _execute_pipeline(playwright_instance)
                else:
                    with sync_playwright() as pw:
                        res = _execute_pipeline(pw)

            if res.get("status") == "cancelled" or _combined_cancel_checker():
                job.status = "cancelled"
                job.error = "Job cancelled during execution"
                self.logger(f"Job {job_id} was cancelled during pipeline execution.")
            else:
                job.status = "completed"
                job.completed_at = datetime.now().isoformat()
                job.result = res
                self.logger(f"Job {job_id} completed successfully. Downloaded: {res.get('downloaded_count', 0)}")
                # Consolidate master manifest
                self._consolidate_master_manifest(job.output_dir)

            return res

        except Exception as err:
            err_msg = security_isolation.mask_sensitive_data(str(err))
            if _combined_cancel_checker():
                job.status = "cancelled"
                job.error = "Job cancelled during execution"
            else:
                job.status = "failed"
                job.error = err_msg
            self.logger(f"Job {job_id} failed with error: {err_msg}")
            return {
                "status": job.status,
                "job_id": job_id,
                "child_name": job.child_name,
                "error": err_msg,
            }

    def run_job_by_id(self, job_id: str, **kwargs) -> Dict[str, Any]:
        """Convenience alias to execute job by ID."""
        return self.run_job(job_id, **kwargs)

    def run_all_jobs(
        self,
        playwright_instance: Optional[Any] = None,
        headless: bool = True,
        cancel_checker: Optional[Callable[[], bool]] = None,
    ) -> Dict[str, Any]:
        """
        Executes all pending jobs recorded in the orchestrator.
        """
        pending_jobs = [j for j in list(self.jobs.values()) if j.status == "pending"]
        self.logger(f"Executing {len(pending_jobs)} pending extraction job(s)...")

        total_downloaded = 0
        total_skipped = 0
        succeeded = 0
        failed = 0
        cancelled = 0

        for job in pending_jobs:
            res = self.run_job(
                job,
                playwright_instance=playwright_instance,
                headless=headless,
                cancel_checker=cancel_checker,
            )

            status = job.status
            if status == "completed":
                succeeded += 1
                total_downloaded += res.get("downloaded_count", 0)
                total_skipped += res.get("skipped_count", 0)
            elif status == "cancelled":
                cancelled += 1
            else:
                failed += 1

        self._consolidate_master_manifest(self.base_output_dir)

        summary = {
            "total_jobs": len(pending_jobs),
            "succeeded": succeeded,
            "failed": failed,
            "cancelled": cancelled,
            "total_downloaded": total_downloaded,
            "total_skipped": total_skipped,
            "master_manifest_path": os.path.join(self.base_output_dir, "manifest.json"),
        }
        self.logger(f"Completed run_all_jobs summary: {summary}")
        return summary

    def run_all_children(
        self,
        user_data_dir: Optional[str] = None,
        output_dir: Optional[str] = None,
        start_date: Optional[str] = None,
        sync_mode: str = "incremental",
        headless: bool = True,
        cancel_checker: Optional[Callable[[], bool]] = None,
        playwright_instance: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Convenience method to auto-discover all children and run extraction jobs for each.
        """
        discovered = self.discover_children(
            user_data_dir=user_data_dir,
            playwright_instance=playwright_instance,
            headless=headless,
        )

        for child in discovered:
            self.submit_job(
                child_name=child.get("name", "general"),
                dependent_id=child.get("dependent_id", ""),
                user_data_dir=user_data_dir,
                output_dir=output_dir,
                start_date=start_date,
                sync_mode=sync_mode,
            )

        return self.run_all_jobs(
            playwright_instance=playwright_instance,
            headless=headless,
            cancel_checker=cancel_checker,
        )

    def orchestrate_extraction(
        self,
        user_data_dir: Optional[str] = None,
        output_dir: Optional[str] = None,
        target_child: Optional[str] = None,
        start_date: Optional[str] = None,
        sync_mode: str = "incremental",
        headless: bool = True,
        cancel_checker: Optional[Callable[[], bool]] = None,
        playwright_instance: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        High-level extraction orchestrator entrypoint. Auto-discovers children,
        filters target child if requested, enqueues jobs, and executes them.
        """
        src_user_data = user_data_dir or self.base_user_data_dir
        src_output = output_dir or self.base_output_dir

        discovered = self.discover_children(
            user_data_dir=src_user_data,
            playwright_instance=playwright_instance,
            headless=headless,
        )

        target_children = []
        if target_child:
            clean_target = target_child.strip().lower()
            target_children = [
                c for c in discovered
                if clean_target in c.get("name", "").lower() or clean_target in c.get("full_name", "").lower()
            ]

            if not target_children:
                self.logger(f"Target child '{target_child}' not matched in auto-discovery. Creating direct job.")
                target_children = [{"name": target_child, "dependent_id": "default"}]
        else:
            target_children = discovered if discovered else [{"name": "Byron", "dependent_id": "default"}]

        for child in target_children:
            self.submit_job(
                child_name=child.get("name", target_child or "Byron"),
                dependent_id=child.get("dependent_id", "default"),
                user_data_dir=src_user_data,
                output_dir=src_output,
                start_date=start_date,
                sync_mode=sync_mode,
            )

        return self.run_all_jobs(
            playwright_instance=playwright_instance,
            headless=headless,
            cancel_checker=cancel_checker,
        )

    def _consolidate_master_manifest(self, base_output_dir: str):
        """
        Consolidates child manifest entries into <base_output_dir>/manifest.json.
        """
        master_path = os.path.join(base_output_dir, "manifest.json")
        master_manifest = {}

        if os.path.exists(master_path):
            try:
                with open(master_path, "r", encoding="utf-8") as f:
                    master_manifest = json.load(f)
            except Exception:
                master_manifest = {}

        # Search base_output_dir and subdirectories for manifest.json files
        if os.path.exists(base_output_dir):
            for root, _, files in os.walk(base_output_dir):
                for fname in files:
                    if fname == "manifest.json":
                        fpath = os.path.join(root, fname)
                        if os.path.abspath(fpath) == os.path.abspath(master_path):
                            continue
                        try:
                            with open(fpath, "r", encoding="utf-8") as f:
                                child_manifest = json.load(f)
                            if isinstance(child_manifest, dict):
                                master_manifest.update(child_manifest)
                        except Exception:
                            pass

        # Also merge entries from completed jobs in memory
        for job in self.jobs.values():
            if job.status == "completed" and job.result and "manifest" in job.result:
                master_manifest.update(job.result["manifest"])

        os.makedirs(base_output_dir, exist_ok=True)
        try:
            with open(master_path, "w", encoding="utf-8") as f:
                json.dump(master_manifest, f, indent=2)
            self.logger(f"Consolidated master manifest at {master_path} with {len(master_manifest)} items.")
        except Exception as err:
            self.logger(f"Failed to write master manifest to {master_path}: {err}")
