# Milestone 3 Analysis: Multi-Tenant / Multi-Child Orchestrator & Runnable CLI Demo

## Executive Summary
This document provides the architectural analysis, design specifications, and implementation plan for Milestone 3:
1. `backend/multi_tenant.py`: `MultiTenantOrchestrator` class managing concurrent, isolated extraction jobs across multiple child profiles and parent accounts without Chromium lock collisions.
2. `demo_scrape_byron.py`: A self-contained, runnable CLI entrypoint demonstrating Byron photo/video extraction using the modular architecture (`dom_parser`, `security_isolation`, `pipeline`, `multi_tenant`).
3. `backend/tests/test_multi_tenant.py`: A comprehensive unit test plan to verify orchestrator behavior, profile isolation, child discovery, error handling, cancellation, and master manifest aggregation.

---

## 1. `backend/multi_tenant.py` Component Design

### 1.1 Architectural Overview
The `MultiTenantOrchestrator` coordinates extraction across multiple children and parent accounts. It acts as the high-level manager that connects:
- **`backend/security_isolation.py`**: `IsolatedUserDataContext` for safe profile cloning, avoiding Playwright/Chromium singleton lock collisions (`SingletonLock`, `RunningChromeVersion`, `*Lock*`).
- **`backend/dom_parser.py`**: `discover_children_from_family_info` for auto-detecting active children via Angular CDK overlays on `familyinfocenter.brighthorizons.com`.
- **`backend/pipeline.py`**: `run_extraction_pipeline` for executing the 11-step extraction workflow (session verification, timeframe navigation, feed parsing, media fetch, EXIF/PNG tEXt chunk injection, Eastern Time `utime` setting, and manifest generation).

```
                  ┌──────────────────────────────────────────────┐
                  │          MultiTenantOrchestrator             │
                  └──────────────────────┬───────────────────────┘
                                         │
                 ┌───────────────────────┼───────────────────────┐
                 ▼                       ▼                       ▼
   ┌───────────────────────────┐ ┌───────────────┐ ┌───────────────────────────┐
   │  Child Auto-Discovery     │ │ Enqueue Jobs  │ │  Isolated Job Runner      │
   │  (dom_parser.py)          │ │ (Job Queue)   │ │  (IsolatedUserDataContext)│
   └─────────────┬─────────────┘ └───────┬───────┘ └─────────────┬─────────────┘
                 │                       │                       │
                 └───────────────────────┼───────────────────────┘
                                         ▼
                        ┌─────────────────────────────────┐
                        │ run_extraction_pipeline         │
                        │ (pipeline.py per child)         │
                        └────────────────┬────────────────┘
                                         ▼
                        ┌─────────────────────────────────┐
                        │ Master Manifest Aggregation &   │
                        │ Path Sanitization               │
                        └─────────────────────────────────┘
```

### 1.2 Data Structures

#### `ExtractionJob` Class
```python
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from datetime import datetime

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
```

### 1.3 `MultiTenantOrchestrator` Class Interface
```python
class MultiTenantOrchestrator:
    def __init__(
        self,
        base_user_data_dir: str = "./user_data",
        base_output_dir: str = "./data",
        max_concurrent_jobs: int = 1,
        sync_back_state: bool = True,
        logger: Optional[Callable[[str], None]] = None
    ):
        ...
```

#### Key Methods:

1. **`discover_children(user_data_dir: Optional[str] = None, headless: bool = True) -> List[Dict[str, str]]`**
   - Resolves source `user_data_dir` (defaulting to `self.base_user_data_dir`).
   - Enters `IsolatedUserDataContext(source_dir, sync_back_state=False)` to prevent singleton lock errors.
   - Launches Playwright persistent context on the isolated directory.
   - Invokes `dom_parser.discover_children_from_family_info(page, context, logger=self.logger)`.
   - Returns discovered list of child profile dictionaries: `[{"name": "Byron", "given_name": "Byron", "full_name": "Byron Taccani Massarelli", "dependent_id": "dep123"}, ...]`.

2. **`create_job(child_name: str, dependent_id: str, user_data_dir: Optional[str] = None, output_dir: Optional[str] = None, start_date: Optional[str] = None, sync_mode: str = "incremental", tenant_id: str = "default_tenant") -> ExtractionJob`**
   - Sanitizes `child_name` via `security_isolation.sanitize_child_name`.
   - Resolves safe output path for child directory under `output_dir` (or `self.base_output_dir`).
   - Instantiates an `ExtractionJob` with status `"pending"`.
   - Appends job to orchestrator job queue (`self.jobs`).

3. **`run_job(job: ExtractionJob, playwright_instance: Optional[Any] = None, headless: bool = True, cancel_checker: Optional[Callable[[], bool]] = None) -> Dict[str, Any]`**
   - Updates `job.status = "running"`.
   - Enters `IsolatedUserDataContext(job.user_data_dir, sync_back_state=self.sync_back_state)` to spawn a clean Chromium environment.
   - Launches Playwright persistent browser context.
   - Calls `pipeline.run_extraction_pipeline(...)` passing `job.child_name`, `job.dependent_id`, `job.output_dir`, `job.start_date`, `job.sync_mode`, `cancel_checker`, and `logger`.
   - Handles exceptions gracefully: sets `job.status = "failed"`, logs masked error message using `security_isolation.mask_sensitive_data`, and records error summary.
   - On success: sets `job.status = "completed"`, `job.completed_at = datetime.now().isoformat()`, and stores pipeline result in `job.result`.
   - Closes browser context and page cleanly.

4. **`run_all_jobs(playwright_instance: Optional[Any] = None, headless: bool = True, cancel_checker: Optional[Callable[[], bool]] = None) -> Dict[str, Any]`**
   - Iterates through pending jobs.
   - Executes jobs using single-threaded sequential runner or bounded worker thread pool (governed by `max_concurrent_jobs`).
   - Aggregates metrics: `total_jobs`, `succeeded`, `failed`, `cancelled`, `total_downloaded`, `total_skipped`.
   - Aggregates individual child manifests into a master `manifest.json` under `base_output_dir`.

5. **`orchestrate_extraction(user_data_dir: str, output_dir: str, target_child: Optional[str] = None, start_date: Optional[str] = None, sync_mode: str = "incremental", headless: bool = True, cancel_checker: Optional[Callable[[], bool]] = None) -> Dict[str, Any]`**
   - High-level end-to-end orchestration entrypoint.
   - Step 1: Calls `discover_children` to discover available active child profiles.
   - Step 2: Filters discovered children if `target_child` is specified (e.g. matching `"Byron"` case-insensitively). If target child is specified but discovery returns empty or missing match, falls back to target child name with existing session.
   - Step 3: Enqueues an `ExtractionJob` per target child.
   - Step 4: Calls `run_all_jobs` and returns aggregated summary dictionary.

---

## 2. Specification for `demo_scrape_byron.py` CLI Demo

### 2.1 Overview
`demo_scrape_byron.py` is a runnable CLI script demonstrating the Byron photo extraction pipeline using the modular V2 architecture.

### 2.2 CLI Interface & Command Line Options
```bash
python demo_scrape_byron.py [OPTIONS]
```

#### Options:
- `--user-data-dir PATH`: Path to persistent Playwright browser profile directory (default: `./user_data`).
- `--output-dir PATH`: Base directory for downloaded photos, videos, and manifests (default: `./data`).
- `--start-date YYYY-MM-DD`: Optional filter to skip posts published prior to this date.
- `--sync-mode {incremental,full}`: Sync strategy (default: `incremental`).
- `--child NAME`: Child name filter (default: `Byron`).
- `--headful`: Run browser in visible/headful mode (default: False/headless).
- `--log-level {DEBUG,INFO,WARNING,ERROR}`: Log level verbosity (default: `INFO`).

### 2.3 Execution Sequence in `demo_scrape_byron.py`

1. **CLI Argument Parsing & Validation:**
   - Parse flags using `argparse`.
   - Validate `--start-date` format (`YYYY-MM-DD`) if provided.
   - Initialize `SanitizedLogger` wrapping `print` / `logging.getLogger` to ensure passwords/MFA/tokens are never printed.

2. **Directory & Singleton Lock Pre-Check:**
   - Log target `--user-data-dir` and `--output-dir`.
   - Confirm user data directory exists or log warning if starting from fresh profile.

3. **Orchestrator Execution:**
   - Instantiate `MultiTenantOrchestrator`:
     ```python
     orchestrator = MultiTenantOrchestrator(
         base_user_data_dir=args.user_data_dir,
         base_output_dir=args.output_dir,
         sync_back_state=True,
         logger=sanitized_log
     )
     ```
   - Invoke `orchestrator.orchestrate_extraction`:
     - Discovers active child profiles (e.g. Byron, Catherine).
     - Filters for Byron.
     - Runs extraction using `IsolatedUserDataContext` (isolating `user_data` directory to prevent Chromium lock collisions).
     - Navigates timeframe tiles (`click_timeframe_tile` on `div.tile.pointable`).
     - Scopes feed extraction inside `div.well.left-panel.pull-left`.
     - Handles video background URLs via CSS parsing fallback.
     - Injects PNG `tEXt` / JPEG EXIF metadata comments.
     - Sets Eastern Time file timestamps (`set_eastern_utime` to 10:00 AM NY time).
     - Saves photos to `<output_dir>/media/Byron/<filename>` and updates `manifest.json`.

4. **Fallback Handling for Offline / Direct Navigation:**
   - If auto-discovery finds no children (e.g., in offline test mode without network), `demo_scrape_byron.py` falls back to querying the existing page URL or creating a default job for Byron (`dependent_id` auto-resolved or passed via parameter) to ensure a smooth demo run.

5. **Console Summary & Diagnostic Output:**
   - Print clean summary table:
     - Target Child: Byron
     - Total Feed Items Processed
     - Photos/Videos Downloaded
     - Items Skipped (Incremental / Date filter)
     - Master Manifest Location
     - Status: SUCCESS / COMPLETED

---

## 3. Security, Lock Isolation, and Boundary Enforcement

| Risk / Requirement | Mitigation Strategy | Implementation Details |
|--------------------|---------------------|------------------------|
| **Chromium Singleton Lock Collision** | Profile cloning with pattern exclusions | `IsolatedUserDataContext` uses `rsync` / `shutil` excluding `Singleton*`, `RunningChromeVersion`, `*Lock*`. |
| **Credential & MFA Code Leakage** | Sanitized logging wrapper | All logs route through `SanitizedLogger` & `mask_sensitive_data`. |
| **Path Traversal & Tenant Escapes** | Canonical path validation & sanitization | Child folder names sanitized with `sanitize_child_name`; paths validated with `canonicalize_and_validate_path`. |
| **Timezone & DST Misalignment** | NY Eastern Time stamping | `set_eastern_utime` strictly calculates epoch for 10:00 AM in `America/New_York`. |
| **Angular CDK Menu Mis-targeting** | Scope-restricted locators | Auto-discovery matches `span.actions-menu-item-label` with exact text "My Bright Day" (Rule 5). |

---

## 4. Unit Test Plan for `backend/tests/test_multi_tenant.py`

### 4.1 Test Suite Breakdown

#### Category 1: `ExtractionJob` Data Model & State Transitions
- `test_extraction_job_instantiation()`: Verify default fields, timestamp creation, and status initialization (`pending`).
- `test_extraction_job_status_transitions()`: Verify status updates (`pending` -> `running` -> `completed` / `failed` / `cancelled`).

#### Category 2: Child Auto-Discovery Integration
- `test_discover_children_success()`: Mock Playwright page & context, mock `dom_parser.discover_children_from_family_info` returning child profiles (`Byron`, `Catherine`). Verify `discover_children` uses `IsolatedUserDataContext` and returns formatted list.
- `test_discover_children_empty_fallback()`: Mock auto-discovery returning empty list. Verify graceful fallback and empty list return without crashing.

#### Category 3: Single & Multi-Child Job Execution
- `test_run_job_single_child_success()`: Mock `run_extraction_pipeline` returning successful result. Execute `run_job` for Byron. Verify job status is `completed`, pipeline is called with sanitized parameters, and results are captured.
- `test_run_job_pipeline_failure()`: Mock `run_extraction_pipeline` raising `RuntimeError("Unauthenticated session")`. Execute `run_job`. Verify job status is set to `failed`, error string is sanitized, and exception does not bubble up unhandled.
- `test_run_job_cancellation()`: Pass `cancel_checker=lambda: True`. Verify job is cancelled and status is updated to `cancelled`.

#### Category 4: Concurrency & Profile Isolation
- `test_profile_isolation_no_lock_collisions()`: Verify `run_job` executes inside an ephemeral `user_data` directory created by `IsolatedUserDataContext` that excludes lock files (`SingletonLock`).
- `test_run_all_jobs_sequential()`: Enqueue jobs for Byron and Catherine. Call `run_all_jobs`. Verify both jobs complete, metrics are aggregated, and `total_downloaded` reflects the sum of downloads.

#### Category 5: Path Traversal & Name Sanitization Safety
- `test_create_job_adversarial_child_name()`: Attempt `create_job` with child names like `../../etc/passwd` or `Byron/../Catherine`. Verify child name is sanitized to safe path and target directory stays within base output dir.

#### Category 6: Master Manifest Aggregation
- `test_master_manifest_consolidation()`: Run jobs producing separate child manifest entries. Verify `run_all_jobs` merges child entries into `<base_output_dir>/manifest.json` without data loss or overwriting valid entries.

---

## 5. Verification Method

### 5.1 Automated Unit Tests
To verify the implementation of `backend/multi_tenant.py` and its test suite:
```bash
pytest backend/tests/test_multi_tenant.py -v
```

To run all unit tests in the project suite:
```bash
pytest backend/tests/ -v
```

### 5.2 CLI Demo Verification
To verify `demo_scrape_byron.py` CLI interface:
```bash
python demo_scrape_byron.py --help
```

To run a dry run CLI demo invocation:
```bash
python demo_scrape_byron.py --user-data-dir ./user_data --output-dir ./data --child Byron --sync-mode incremental
```
