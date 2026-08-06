---
name: brighthorizon-extractor
description: Sync, verify, and organize child photo and video downloads from the Bright Horizons parent portal via the multi-tenant web API and Playwright scraper engine.
---

# Bright Horizons Extractor Skill

Use this skill when running extraction, testing scraper logic, managing tenant data, or verifying media syncs from the Bright Horizons parent portal.

## Workspace & Environment Requirements

1. **Playwright Chromium**: Installed via `uv run playwright install chromium`.
2. **Environment Variables**:
   - `DATA_DIR`: Set to `/data` in Docker container or defaults to `./data` on host.
   - `APP_SECRET`: Optional master secret override for key derivation.

## Architecture & Workflows

### 1. Multi-Tenant REST API (`backend/server.py`)
- Authentication (`POST /api/auth/login`, `POST /api/auth/mfa`, `POST /api/auth/purge`)
- Media Retrieval (`GET /api/media`, `GET /api/media/{media_id}`)
- Extraction Jobs (`POST /api/extraction/start`, `GET /api/extraction/status`, `POST /api/extraction/cancel`)
- Archives (`POST /api/archive/create`, `GET /api/archive/status`, `GET /api/archive/download`)

### 2. Running Backend Tests
Always execute unit tests using `uv run pytest backend/tests/` to verify security isolation, DOM parsing, and pipeline concurrency:
```bash
uv run pytest backend/tests/
```

### 3. Versioning & Deployment Workflow
Before every container build or commit:
1. Run version bump script:
   ```bash
   python3 scripts/bump_version.py
   ```
2. Rebuild and restart Docker containers:
   ```bash
   docker compose build && docker compose up -d
   ```
3. Run post-deployment HTTP verification:
   ```bash
   python3 scripts/verify_deployment.py https://bears.ceoloide.com
   ```

## Critical Gotchas & DOM Guidance

1. **Playwright Persistent Context Lock**:
   Playwright uses `./user_data/` for session state. Never run parallel diagnostic scripts against `./user_data/` while a container or scraper background job is running.
2. **Timeframe Ready Check**:
   Always wait for `i.fa-spinner` visibility to clear and verify thumbnail cards before extracting DOM images (`wait_for_month_feed_ready`).
3. **Primary Download Sanitization**:
   Always strip `thumbnail=true` query parameters using `clean_full_res_url()` to prevent downloading low-resolution 200×200 thumbnails as full photo assets.
4. **Single ZIP Archive Enforcement**:
   At most one archive ZIP file exists per tenant. Creating a new archive purges previous ZIP files and computes a SHA-256 hash of the manifest content.
