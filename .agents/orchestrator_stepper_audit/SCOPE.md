# Scope: Manual Stepper, Turnstile Flow & Session Persistence Audit

## Architecture & Audit Focus
Target codebase: `/home/antigravity/GitHub/brighthorizon-photo-extractor`
Core files under audit:
- `backend/scraper_engine.py`
- `backend/server.py`

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Manual Substep Stepping Enforcement Audit | Inspect `perform_login()` in `backend/scraper_engine.py` for `wait_for_manual_step()` calls before typing email, before submitting email/Turnstile, and before submitting password. Verify thread waiting on `POST /api/auth/next-step`. | None | IN_PROGRESS |
| 2 | Turnstile Timing Audit | Verify Turnstile solving logic timing relative to email typing completion and `wait_for_manual_step` trigger. | M1 | IN_PROGRESS |
| 3 | Session & Live Preview Persistence Audit | Inspect `backend/server.py` for session timeout cleanup retaining live preview screenshots and job references. | M1 | IN_PROGRESS |
| 4 | Final Report & Forensic Audit | Synthesize findings into `audit_report.md`, run forensic audit & challenger verification. | M1, M2, M3 | PLANNED |

## Code Layout Under Audit
- `backend/scraper_engine.py` - Scraper engine login stepper flow & Turnstile solver interaction
- `backend/server.py` - FastAPI application, session state management, live preview endpoints, and cleanup timeouts
