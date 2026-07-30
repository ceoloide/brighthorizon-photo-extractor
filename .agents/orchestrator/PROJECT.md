# Security Audit Project: Desktop-Only Session Import & Device Cookie Authentication Flow

## Architecture & Scope
Audit target: `brighthorizon-photo-extractor` session import and authentication mechanisms.

## Specific Audit Focus Areas:
1. **Mobile Device Guardrail**:
   - Inspect UA + `window.innerWidth` detection logic.
   - Evaluate reliability and potential bypass vectors (e.g. spoofing UA, viewport resizing, devtools emulation, touch API polyfills).

2. **Address Bar JavaScript Snippet & Client-Side Validation**:
   - Payload format: `{cookies: document.cookie, storage: JSON.stringify(localStorage)}`.
   - React validation logic for JSON parsing.
   - Verification of required cookie keys (`auth0`, `dtCookie`, `OptanonConsent`, `_ga`) and LocalStorage items (`_pendo_meta`, `_fs_uid`).
   - Exception handling & crash prevention.

3. **Multi-Tenant Device Cookie (`bh_tenant_token`)**:
   - Properties: HTTP-Only, Secure, SameSite=Lax.
   - Encryption / signing via JWT secret.
   - Strict scoping to `tenant_id` to prevent cross-tenant session leaks, token forgery, or replay attacks.

4. **Playwright Session Restoration (`ScraperJob`)**:
   - `storage_state.json` loading and parsing.
   - Graceful handling of expired/missing cookies.
   - Execution of `discover_children` and media scraping without hitting login redirects.

## Audit Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | Codebase Discovery & Analysis | Locating and inspecting session import, validation, cookie handling, and Playwright integration | None | IN_PROGRESS |
| 2 | Vulnerability & Defense Evaluation | In-depth analysis of 4 target areas against adversarial vectors | M1 | PLANNED |
| 3 | Report Generation | Compiling comprehensive audit report into `security_audit_report.md` | M2 | PLANNED |

## Deliverable Path
`.agents/orchestrator/security_audit_report.md`
