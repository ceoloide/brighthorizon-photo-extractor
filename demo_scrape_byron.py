#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""
CLI Demo Entrypoint Script for Bright Horizons Byron Photo Extraction.

Demonstrates complete Byron photo & video extraction pipeline execution using
MultiTenantOrchestrator, IsolatedUserDataContext, and SanitizedLogger.
Spec reference: .agents/explorer_m3/analysis.md
"""

import argparse
import sys
import os
from datetime import datetime

from backend import security_isolation
from backend.multi_tenant import MultiTenantOrchestrator


def parse_args():
    parser = argparse.ArgumentParser(
        description="Bright Horizons Photo Extractor CLI Demo - Byron Sync"
    )
    parser.add_argument(
        "--user-data-dir",
        default="./user_data",
        help="Path to persistent Playwright browser profile directory (default: ./user_data)",
    )
    parser.add_argument(
        "--output-dir",
        default="./downloads",
        help="Base directory for downloaded photos, videos, and manifests (default: ./downloads)",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help="Optional filter start date (YYYY-MM-DD) to skip older posts",
    )
    parser.add_argument(
        "--sync-mode",
        choices=["incremental", "full"],
        default="incremental",
        help="Sync mode: 'incremental' (stop on existing) or 'full' (scan all history)",
    )
    parser.add_argument(
        "--child",
        default="Byron",
        help="Child name to filter for extraction (default: Byron)",
    )
    parser.add_argument(
        "--dependent-id",
        default=None,
        help="Optional explicit dependent_id override for target child",
    )
    parser.add_argument(
        "--headful",
        action="store_true",
        help="Run browser in visible headful mode (default: False/headless)",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Validate start_date format if provided
    if args.start_date:
        try:
            datetime.strptime(args.start_date, "%Y-%m-%d")
        except ValueError:
            print(f"Error: Invalid --start-date format '{args.start_date}'. Must be YYYY-MM-DD.")
            sys.exit(1)

    # Initialize SanitizedLogger wrapper
    def _console_logger(msg: str):
        print(f"[DEMO LOG] {msg}")

    sanitized_logger = security_isolation.SanitizedLogger(_console_logger)
    log = sanitized_logger.log

    log("=" * 70)
    log("Bright Horizons Photo Extractor — Milestone 3 Byron CLI Demo")
    log("=" * 70)
    log(f"Target Child        : {args.child}")
    log(f"User Data Directory : {os.path.abspath(args.user_data_dir)}")
    log(f"Output Directory    : {os.path.abspath(args.output_dir)}")
    log(f"Sync Mode           : {args.sync_mode}")
    log(f"Start Date Filter   : {args.start_date or 'None'}")
    log(f"Headless Mode       : {not args.headful}")
    log("-" * 70)

    # Pre-check user data directory existence
    if not os.path.exists(args.user_data_dir):
        log(f"Warning: Specified user_data_dir '{args.user_data_dir}' does not exist.")
        log("If starting from a fresh profile, portal navigation will require authentication.")

    # Instantiate MultiTenantOrchestrator
    orchestrator = MultiTenantOrchestrator(
        base_user_data_dir=args.user_data_dir,
        base_output_dir=args.output_dir,
        sync_back_state=True,
        logger=log,
    )

    try:
        # Run extraction pipeline for target child
        summary = orchestrator.orchestrate_extraction(
            user_data_dir=args.user_data_dir,
            output_dir=args.output_dir,
            target_child=args.child,
            start_date=args.start_date,
            sync_mode=args.sync_mode,
            headless=not args.headful,
        )

        log("=" * 70)
        log("EXTRACTION SUMMARY RESULTS")
        log("=" * 70)
        log(f"Total Enqueued Jobs : {summary.get('total_jobs', 0)}")
        log(f"Succeeded Jobs      : {summary.get('succeeded', 0)}")
        log(f"Failed Jobs         : {summary.get('failed', 0)}")
        log(f"Cancelled Jobs      : {summary.get('cancelled', 0)}")
        log(f"Photos Downloaded   : {summary.get('total_downloaded', 0)}")
        log(f"Items Skipped       : {summary.get('total_skipped', 0)}")
        log(f"Master Manifest     : {summary.get('master_manifest_path')}")
        log("=" * 70)

        if summary.get("failed", 0) > 0:
            log("Execution completed with errors. See log messages above.")
            sys.exit(1)
        else:
            log("Extraction pipeline executed successfully!")
            sys.exit(0)

    except Exception as err:
        clean_err = security_isolation.mask_sensitive_data(str(err))
        log(f"Fatal error during CLI execution: {clean_err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
