# Execution Plan: Bright Horizons Auth & Extraction Investigation and Fix

## Overview
Decomposed into 4 sequential & integrated milestones to address user requirements R1, R2, R3, R4.

## Phase 1: Exploration
Spawn 3 parallel Explorers:
- **Explorer 1**: Investigate current logging, network event tracing, and server log output (`backend/server.py`, `backend/scraper_engine.py`, Playwright event listeners).
- **Explorer 2**: Investigate Turnstile challenge detection (`solve_and_wait_turnstile`), stall points (50s timeouts), and Auth0 credential entry timing.
- **Explorer 3**: Investigate cross-domain session cookie handling, OAuth handshake with `mybrightday.brighthorizons.com`, `storage_state.json` persistence, `discover_children`, and media extraction request authorization (avoiding 401/403).

## Phase 2: Implementation & Verification Loop per Milestone
- Milestone 1: Deep Logging & Network Tracing
  - Worker implementation -> Reviewers (2) -> Challengers (2) -> Forensic Auditor -> Gate
- Milestone 2: Turnstile Fast-Path & Auth0 Credential Entry
  - Worker implementation -> Reviewers (2) -> Challengers (2) -> Forensic Auditor -> Gate
- Milestone 3: Cross-Domain Session Persistence & Media Extraction
  - Worker implementation -> Reviewers (2) -> Challengers (2) -> Forensic Auditor -> Gate
- Milestone 4: E2E Verification & Live System Verification
  - Worker execution of E2E tests -> Reviewers -> Victory Auditor report

## Gate Pass Criteria
1. All builds and unit/integration tests pass.
2. Reviewers approve.
3. Challengers confirm empirical behavior.
4. Forensic Auditor verdict is CLEAN (Zero Tolerance for integrity violations/facades).
