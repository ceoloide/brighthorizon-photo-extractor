# Explorer 1 Scope

Investigation of:
1. Mobile Device Guardrail implementation (UA, window.innerWidth, bypass resistance).
2. Address Bar JS Snippet & Client-Side Validation logic (JSON parsing, cookie key checks: `auth0`, `dtCookie`, `OptanonConsent`, `_ga`; LocalStorage checks: `_pendo_meta`, `_fs_uid`; robustness against crashes).
3. Multi-Tenant Device Cookie (`bh_tenant_token`) implementation (HTTP-Only, Secure, SameSite=Lax, JWT encryption, tenant_id scoping).
4. Playwright Session Restoration (`ScraperJob`, `storage_state.json`, expired cookie handling, `discover_children`, redirect avoidance).
