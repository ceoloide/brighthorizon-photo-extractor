# SPDX-License-Identifier: MIT
# Background Scheduler Module for Incremental Extraction Jobs
import os
import time
import threading
from datetime import datetime
from typing import Dict, Any, Optional

from backend.security import get_data_dir, decrypt_json, get_tenant_id
from backend.database import TenantStorage
from backend.scraper_engine import ScraperJob

_last_scheduled_run_date: Optional[str] = None
_scheduler_thread: Optional[threading.Thread] = None
_scheduler_running: bool = False

def scan_and_run_scheduled_jobs(active_jobs: Dict[str, Any]):
    """
    Sequentially scans all encrypted tenant configurations in DATA_DIR/tenants.
    For any user config with `scheduled_incremental: True` and stored credentials,
    launches an incremental extraction job sequentially.
    """
    data_dir = get_data_dir()
    tenants_dir = os.path.join(data_dir, "tenants")
    if not os.path.exists(tenants_dir):
        return

    print("[Scheduler] Scanning tenant configurations for scheduled incremental jobs...")
    try:
        tenant_entries = sorted(os.listdir(tenants_dir))
    except Exception as e:
        print(f"[Scheduler] Error reading tenants directory: {e}")
        return

    for t_folder in tenant_entries:
        t_dir = os.path.join(tenants_dir, t_folder)
        if not os.path.isdir(t_dir):
            continue

        config_file = os.path.join(t_dir, "config.enc")
        if not os.path.exists(config_file):
            continue

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                raw_enc = f.read()
            config = decrypt_json(raw_enc)
        except Exception as e:
            print(f"[Scheduler] Error reading/decrypting config in {t_folder}: {e}")
            continue

        if not isinstance(config, dict):
            continue

        is_scheduled = config.get("scheduled_incremental", False)
        email = config.get("email")
        pwd = config.get("password")

        if is_scheduled and email and pwd:
            tenant_id = get_tenant_id(email)
            if tenant_id in active_jobs and active_jobs[tenant_id].status.get("state") == "running":
                print(f"[Scheduler] Job already running for tenant {tenant_id} ({email}). Skipping scheduled run.")
                continue

            print(f"[Scheduler] Executing scheduled incremental job for {email} ({tenant_id})...")
            tenant_storage = TenantStorage(email)
            options = {
                "sync_mode": "incremental",
                "child": "all",
                "layout_mode": "flat"
            }
            job = ScraperJob(tenant_storage, pwd, options)
            active_jobs[tenant_id] = job
            try:
                # Run synchronously to guarantee sequential execution across scheduled tenants
                job.run()
                print(f"[Scheduler] Completed scheduled incremental job for {email}.")
            except Exception as e:
                print(f"[Scheduler] Exception running scheduled job for {email}: {e}")

def _scheduler_loop(active_jobs: Dict[str, Any]):
    global _last_scheduled_run_date, _scheduler_running
    while _scheduler_running:
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        if now.hour == 18 and 0 <= now.minute <= 15:
            if _last_scheduled_run_date != today_str:
                _last_scheduled_run_date = today_str
                print(f"[Scheduler] Triggering daily 6:00 PM scheduled incremental run for {today_str}")
                try:
                    scan_and_run_scheduled_jobs(active_jobs)
                except Exception as e:
                    print(f"[Scheduler] Scheduled scan failed: {e}")
        time.sleep(30)

def start_background_scheduler(active_jobs: Dict[str, Any]):
    global _scheduler_thread, _scheduler_running
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _scheduler_running = True
    _scheduler_thread = threading.Thread(target=_scheduler_loop, args=(active_jobs,), daemon=True)
    _scheduler_thread.start()
    print("[Scheduler] Background daily 6:00 PM scheduler initialized.")
