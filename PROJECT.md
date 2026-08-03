# Project: Bright Horizons Modular Photo Extractor

## Architecture
Modular Python Playwright extraction suite separating concerns into:
- `backend/dom_parser.py`: DOM parsing (Knockout.js month tiles, feed scoping, fancybox URLs, video background CSS, Angular CDK child auto-discovery).
- `backend/security_isolation.py`: Session persistence, user_data directory lock avoidance via rsync/copying, credential masking, child path scoping.
- `backend/pipeline.py`: Step-by-step extraction workflow (child resolution, timeframe navigation, lazy scrolling, media download, EXIF/PNG tEXt metadata injection, utime Eastern Time setting, manifest writing).
- `backend/multi_tenant.py`: Isolated multi-tenant / multi-child job orchestration avoiding lock contention and session leaks.
- `demo_scrape_byron.py`: Runnable CLI entrypoint demonstrating Byron photo/video extraction with modular components.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Module Architecture & DOM Parser | Implement `backend/dom_parser.py` and `backend/security_isolation.py` | None | DONE |
| 2 | Extraction Pipeline & Asset Metadata | Implement `backend/pipeline.py` (EXIF, PNG tEXt chunk, Eastern Time utime, manifest) | M1 | DONE |
| 3 | Multi-Tenant Orchestrator & CLI Demo | Implement `backend/multi_tenant.py` and `demo_scrape_byron.py` | M2 | IN_PROGRESS |
| 4 | Verification & Audit Gate | Run unit tests, execute demo script, conduct reviewer and forensic audit checks | M3 | PLANNED |

## Interface Contracts
### `backend/dom_parser.py`
- `parse_timeframe_links(page)` -> `list[dict]`
- `click_timeframe_tile(page, tile_element)` -> `None`
- `extract_feed_items(page)` -> `list[dict]` (handles photo vs video background CSS fallback)
- `discover_children_from_family_info(page)` -> `list[dict]`

### `backend/security_isolation.py`
- `prepare_isolated_user_data(source_dir, target_dir)` -> `str`
- `sanitize_path(base_dir, child_name, filename)` -> `str`
- `mask_credentials(text)` -> `str`

### `backend/pipeline.py`
- `inject_jpeg_exif(file_path, comment)` -> `None`
- `inject_png_text_chunk(file_path, comment)` -> `None`
- `set_eastern_utime(file_path, dt_obj)` -> `None`
- `run_extraction_pipeline(page, child_name, dependent_id, output_dir, start_date)` -> `dict`

### `backend/multi_tenant.py`
- `class MultiTenantOrchestrator`: methods for enqueueing and running isolated child extraction jobs.

## Code Layout
- `backend/dom_parser.py`
- `backend/security_isolation.py`
- `backend/pipeline.py`
- `backend/multi_tenant.py`
- `demo_scrape_byron.py`
- `backend/tests/test_modular_scraper.py`
