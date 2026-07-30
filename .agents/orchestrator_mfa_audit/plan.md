# Master Security Audit & Plan: MFA Flow & Scraper Infrastructure

## Architecture & System Overview
The `brighthorizon-photo-extractor` project provides automated media extraction from Bright Horizons parent portals. The newly implemented features under security audit include:
- **Auth0 Email Verification Code (MFA) Flow**: Handling multi-factor authentication codes required during parent portal login.
- **Volatile Memory Zero-Disk Handling**: Ensuring 6-digit MFA codes reside exclusively in thread-volatile memory (`_mfa_code`) and are zeroed/overwritten immediately after use.
- **Session Ownership Verification & Rate Limiting**: Protecting `POST /api/auth/submit-mfa-code` from enumeration, unauthorized submission, or brute-force attacks.
- **Headful Xvfb & Turnstile Bypass**: Launching Playwright Chromium in headful mode using Xvfb (`DISPLAY=:99`) to bypass Cloudflare Turnstile and Auth0 bot detection without singleton lock collisions.
- **Frontend Stepper & Child Auto-Discovery**: UI state machine transitions in `VerificationInterstitial.tsx` and child profile discovery (`discover_children`).

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | M1: Static Security & Memory Handling Audit (R1 & R2) | Audit `backend/scraper_engine.py`, `backend/server.py`, `backend/security.py` for MFA memory handling, logging leaks, session ownership, regex sanitization, and rate limiting logic. | None | PLANNED |
| 2 | M2: Static Audit of Headful Xvfb & UI Stepper (R3 & R4) | Audit `backend/scraper_engine.py`, `frontend/src/components/VerificationInterstitial.tsx` for Xvfb setup, Turnstile frame clicking, singleton lock handling, stepper transitions, and `discover_children` post-MFA. | M1 | PLANNED |
| 3 | M3: Dynamic Verification & Test Suite Execution | Execute existing and targeted dynamic security tests in `backend/tests/` and frontend test suites to verify rate limits, session expiration (120s), memory zeroing, and error handling under load. | M2 | PLANNED |
| 4 | M4: Forensic Integrity Audit & Synthesis | Run `teamwork_preview_auditor` for integrity verification and synthesize findings into `security_audit_report.md`. | M3 | PLANNED |

## Interface Contracts & Requirements Mapping
- **R1 (Volatile Memory & Zero Disk)**: `_mfa_code` in `ScraperEngine` must be set only in memory, never serialized to disk/DB/logs/SSE, cleared with `None` immediately upon ingestion by Playwright.
- **R2 (Session Ownership & Rate Limiting)**: `POST /api/auth/submit-mfa-code` requires authenticated tenant session token matching active scraper session; inputs matching `^[0-9]{6}$`; strictly limited to max 3 attempts per 120s window.
- **R3 (Headful Xvfb & Turnstile)**: Chromium launched with `headless=False`, using `DISPLAY=:99`, iframe selector `cf_frame.click("body", position={"x": 30, "y": 30})`, lock isolation using per-tenant user data copy directory.
- **R4 (E2E Stepper & Child Discovery)**: SSE event `mfa_required` triggers UI prompt in `VerificationInterstitial.tsx`, code submission advances login, followed by `discover_children()` trigger.

## Code Layout
- `backend/scraper_engine.py`: Scraper engine, Playwright logic, MFA code handling, Xvfb/Turnstile handling, child discovery.
- `backend/server.py`: FastAPI server, REST routes (`/api/auth/submit-mfa-code`), SSE stream publishing.
- `backend/security.py`: Session management, token validation, rate limiting counters.
- `backend/tests/`: Pytest suite for API security, rate limiting, and scraper functionality.
- `frontend/src/components/VerificationInterstitial.tsx`: React UI component for MFA verification prompt and stepper state.
