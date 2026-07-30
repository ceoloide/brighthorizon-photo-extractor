# Security Audit Project: Background Job Engine, Start Date Filtering, Single-Job Enforcement, & Progress Reporting

## Architecture & Scope
Audit target: `brighthorizon-photo-extractor` extraction engine, API server, job cancellation, date filtering, multi-tenant isolation, and flat storage.

## Specific Audit Focus Areas:
1. **Single-Job Per User Enforcement & Cancellation Safety**:
   - `POST /api/extraction/start` concurrent request handling and race conditions for the same `tenant_id`.
   - `job.cancel()` implementation: Playwright context cleanup, chromium process termination, singleton lock file release (`user_data` / `user_data_copy`), deadlock prevention, and zombie process checks.

2. **Custom Start Date Filtering**:
   - Date parsing and timezone conversion in `extract_child_feed`.
   - Filtering accuracy of post dates against `start_date` across Eastern Time (ET) / UTC boundaries, DST transitions, and edge cases.

3. **Progress Reporting & Metric Privacy**:
   - Tenant isolation of live progress metrics (`current_child`, `current_month`, `current_date`, `downloaded_count`, etc.) in `_active_jobs`.
   - SSE / API endpoint privacy: prevention of cross-tenant metric leaks or unauthenticated access to job status.

4. **Flat Storage Enforcement & Backward Compatibility**:
   - Deprecation / removal of `layout_mode` parameter from UI and backend defaulting to flat mode (`downloads/<child_name>/...`).
   - Backward compatibility with pre-existing `manifest.json` schemas, directory layouts, and ZIP archive creation (`archive_stream.py`).

## Audit Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Codebase Discovery & Analysis | Locating and inspecting extraction endpoints, job management, scraper engine, and archive generation | None | IN_PROGRESS |
| 2 | Adversarial Risk & Security Evaluation | Deep analysis of concurrency, cancellation, timezone filtering, tenant privacy, and flat storage | M1 | PLANNED |
| 3 | Verification & Review | Reviewing audit findings with reviewer/auditor agents | M2 | PLANNED |
| 4 | Comprehensive Report Compilation | Synthesizing findings into security audit report | M3 | PLANNED |

## Deliverable Path
`.agents/orchestrator_job_engine/security_audit_report.md`
