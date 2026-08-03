# Analysis Report: Deep Logging & Network Tracing (Requirement R1)

**Investigator**: Explorer 1 (Deep Logging & Network Tracing Specialist)  
**Target Milestone**: Milestone 1 (Requirement R1)  
**Date**: 2026-08-03  
**Working Directory**: `/home/antigravity/GitHub/brighthorizon-photo-extractor/.agents/explorer_r1`

---

## Executive Summary

An in-depth investigation of `backend/server.py`, `backend/scraper_engine.py`, `backend/pipeline.py`, `main.py`, and Playwright context creation code was conducted to evaluate current logging capabilities and identify gaps during authentication, Turnstile challenge handling, child discovery, and media downloads.

Currently:
1. **Playwright context network events** (`request`, `response`, `requestfailed`) are **completely unmonitored** in `backend/scraper_engine.py` and `backend/pipeline.py`.
2. Logging in `backend/scraper_engine.py` is string-based and stored in a sliding memory buffer (`self.status["logs"]`, capped at 200 strings), losing structured metadata (status codes, response headers, Set-Cookie directives, target domains, timing, request IDs).
3. Critical transition points—such as Auth0 SSO redirects, Cloudflare Turnstile token arrivals, Angular CDK overlay interactions, and media download HTTP status codes (200 vs 401/403)—are either logged via high-level `print`/`self.log` strings or not logged at all.

This report presents a detailed audit of existing logging mechanisms, pinpoints missing coverage across 5 operational phases, and proposes a complete, concrete implementation strategy for adding structured deep logging and Playwright network event tracing.

---

## 1. Inspection & Audit of Current Logging Architecture

### A. `backend/server.py`
- **FastAPI Endpoints**: Relies on default Uvicorn loggers and occasional `print()` statements (e.g., lines 264, 266 during job cancellation in `/api/auth/logout`).
- **Progress Streaming**:
  - `/api/auth/verify-stream` (lines 153–191) streams `_active_verifications[tenant_id]` state over Server-Sent Events (SSE).
  - `/api/extraction/events` (lines 380–405) streams `_active_jobs[tenant_id].status` over SSE.
- **Limitation**: Server endpoints do not record HTTP request headers, cookie exchanges, or Playwright network transactions. When a verification or extraction job fails, the API client only sees a top-level error string (e.g., `"Session expired or invalid"`).

### B. `backend/scraper_engine.py`
- **`ScraperJob.log(message)`** (lines 147–153):
  ```python
  def log(self, message: str):
      timestamp = datetime.now().strftime("%H:%M:%S")
      entry = f"[{timestamp}] {message}"
      self.status["logs"].append(entry)
      if len(self.status["logs"]) > 200:
          self.status["logs"].pop(0)
      self.log_callback(entry)
  ```
- **Sliding Buffer**: Keeps up to 200 plain text lines. When logs exceed 200, earlier logs are dropped.
- **Playwright Page & Context Creation**:
  - `launch_stealth_persistent_context()` (lines 57–93) creates persistent browser contexts.
  - **Zero network listeners attached**: Neither `context.on("request", ...)` nor `page.on("response", ...)` is registered anywhere in `scraper_engine.py`.
- **Media Request Logging**:
  - In `extract_child_feed()` (lines 1149–1178), requests to `page.request.get(download_url)` only log failures (`HTTP {response.status} when fetching obj_id...`). Successful 200 OK responses, signed Cloudflare S3/CDN URLs, Set-Cookie headers, and content lengths are not logged.

### C. `main.py`
- **CLI Logging**: Uses standard Python `print()` statements.
- **Request Listening**: In `discover_children()` (line 578), `page.on('request', on_request)` is registered temporarily to capture `dependent_id` parameters during manual tile clicking. It is immediately detached with `page.remove_listener('request', on_request)`.

### D. `backend/pipeline.py`
- **Extraction Helper**: Contains `run_extraction_pipeline()` with custom `log()` callback, but no Playwright event listeners attached to `page` or `context`.

---

## 2. Gap Analysis Across Critical Workflow Phases

| Phase | Current Behavior | Logging Gaps | Risk / Impact |
|---|---|---|---|
| **1. Initial Page Loads & SSO Redirects** | High-level status logged (e.g., `"Navigating to..."`, `"Saved session expired..."`). | No logging of 302/307 HTTP redirects, origin domain changes (`familyinfocenter` → `bhloginsso.brighthorizons.com` → `auth0`), `Set-Cookie` header attributes (SameSite, Secure, Domain), or network connection failures. | Obscures where SSO session handshakes break down (e.g. lost cookies across origins). |
| **2. Cloudflare Turnstile Challenge Detection** | `solve_and_wait_turnstile()` polls DOM tokens and frame text. | No network event logging for Turnstile API calls (`challenges.cloudflare.com/cdn-cgi/challenge-platform/...`), clearance cookie set events (`cf_clearance`), or HTTP 403 / 429 response codes. | Cannot distinguish between Turnstile iframe render failure, Network block, or JS execution stall. |
| **3. Stepper Transitions & Manual Step Waits** | `detect_page_state()` polls DOM every 1s (lines 356–393). | DOM state transitions are logged as string state values, but without DOM snapshot elements, URL query params, or pending XHR/Fetch request counts. | Hard to diagnose why stepper hangs during Auth0 step transitions. |
| **4. Child Auto-Discovery (`discover_children`)** | Logs card count and discovered child names. | No network tracing of Angular CDK overlay API requests or tab opening URLs (`context.expect_page()`). | Fails silently or skips enrolled children if Angular CDK overlay request fails without error visibility. |
| **5. Media Download Requests** | Logs download start and errors for `obj_id`. | No logging of request headers (Cookie, Authorization), response headers (`Content-Type`, `Content-Length`), HTTP status code breakdown (200 vs 302 vs 401 vs 403), or signed URL redirects. | Difficult to debug why a media item receives 401/403 (unauthorized) vs 404 (not found). |

---

## 3. Concrete Implementation Code Changes for Requirement R1

To achieve comprehensive structured deep logging and network tracing without breaking existing UI SSE format, we propose the following changes:

### Proposal A: Structured Log Entry & Event Listener System in `backend/scraper_engine.py`

#### 1. Define Structured Log Models & Helper Class
Add a structured logging formatter that formats log entries into enriched JSON-compatible dictionaries while preserving human-readable strings for UI display:

```python
# Sub-component to attach to ScraperJob in backend/scraper_engine.py

class NetworkTraceLogger:
    def __init__(self, job: "ScraperJob"):
        self.job = job
        self._enabled = True

    def attach_to_context(self, context: BrowserContext):
        """Attaches network event listeners to Playwright BrowserContext to trace all pages & frames."""
        context.on("request", self._on_request)
        context.on("response", self._on_response)
        context.on("requestfailed", self._on_request_failed)

    def _on_request(self, request):
        url = request.url
        # Filter noise (data URIs, static assets like fonts/css unless auth/media endpoint)
        if url.startswith("data:") or any(ext in url for ext in [".woff", ".woff2", ".ttf", ".svg", ".css"]):
            return
            
        # Highlight high-value target endpoints
        if any(domain in url for domain in ["brighthorizons", "auth0", "cloudflare", "obj_attachment"]):
            headers_summary = {k: (v if k.lower() not in ["authorization", "cookie"] else "[REDACTED]") for k, v in request.headers.items()}
            self.job.log_structured(
                level="DEBUG",
                category="NETWORK_REQ",
                message=f"--> {request.method} {url}",
                details={
                    "method": request.method,
                    "url": url,
                    "resource_type": request.resource_type,
                    "headers": headers_summary
                }
            )

    def _on_response(self, response):
        url = response.url
        if url.startswith("data:") or any(ext in url for ext in [".woff", ".woff2", ".ttf", ".svg", ".css"]):
            return

        if any(domain in url for domain in ["brighthorizons", "auth0", "cloudflare", "obj_attachment"]):
            status = response.status
            # Log set-cookie headers specifically
            set_cookie_headers = [v for k, v in response.headers.items() if k.lower() == "set-cookie"]
            
            details = {
                "status": status,
                "url": url,
                "status_text": response.status_text,
                "set_cookies_count": len(set_cookie_headers)
            }
            if set_cookie_headers:
                details["set_cookies"] = [c.split(";")[0] for c in set_cookie_headers] # Safe log cookie names/keys only

            level = "INFO" if status < 400 else ("WARN" if status < 500 else "ERROR")
            self.job.log_structured(
                level=level,
                category="NETWORK_RESP",
                message=f"<-- HTTP {status} {url}",
                details=details
            )

    def _on_request_failed(self, request):
        url = request.url
        if any(domain in url for domain in ["brighthorizons", "auth0", "cloudflare", "obj_attachment"]):
            failure = request.failure
            self.job.log_structured(
                level="ERROR",
                category="NETWORK_FAIL",
                message=f"X-- FAILED {request.method} {url} | Error: {failure}",
                details={"url": url, "failure": failure}
            )
```

#### 2. Upgrade `ScraperJob.log` to Support Structured Context
Modify `ScraperJob` in `backend/scraper_engine.py`:

```python
def log_structured(self, level: str, category: str, message: str, details: Optional[Dict[str, Any]] = None):
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    entry_str = f"[{timestamp}] [{level}] [{category}] {message}"
    
    structured_entry = {
        "timestamp": timestamp,
        "level": level,
        "category": category,
        "message": message,
        "details": details or {}
    }
    
    # Store in status logs
    self.status["logs"].append(entry_str)
    if len(self.status["logs"]) > 300:
        self.status["logs"].pop(0)
        
    if self.log_callback:
        self.log_callback(entry_str)

def log(self, message: str):
    self.log_structured("INFO", "GENERAL", message)
```

#### 3. Integrate Network Tracing into `run()`, `verify_credentials()`, and `perform_login()`
In `ScraperJob.run()` and `verify_credentials()`:

```python
# Right after creating persistent context:
network_tracer = NetworkTraceLogger(self)
network_tracer.attach_to_context(context)
```

---

## 4. Phase-by-Phase Deep Logging Enhancements

### A. Initial Page Loads & Cross-Domain Redirects (`perform_login`)
Add explicit origin & cookie logging when switching domains:

```python
def log_domain_transition(self, page: Page, stage_name: str):
    cookies = page.context.cookies()
    domain_summary = {}
    for c in cookies:
        d = c.get("domain", "unknown")
        domain_summary[d] = domain_summary.get(d, 0) + 1
        
    self.log_structured(
        level="INFO",
        category="AUTH_STAGE",
        message=f"Transitioning to stage '{stage_name}' | URL: {page.url}",
        details={
            "stage": stage_name,
            "url": page.url,
            "active_domains_cookies": domain_summary
        }
    )
```

### B. Turnstile Challenge & Fast-Path Status (`solve_and_wait_turnstile`)
Log Turnstile frame states, token arrival times, and fast-path bypass status:

```python
# In solve_and_wait_turnstile:
self.log_structured(
    level="INFO",
    category="TURNSTILE",
    message=f"[Turnstile] Check started. Target URL: {page.url}",
    details={"cf_frames": len(cf_frames), "has_input": has_turnstile_input}
)

if token_populated:
    elapsed = round(time.time() - start_t, 2)
    self.log_structured(
        level="INFO",
        category="TURNSTILE",
        message=f"[Turnstile] Fast-Path Clearance Detected! Token populated in {elapsed}s",
        details={"elapsed_sec": elapsed, "fast_path": True}
    )
```

### C. Stepper Transitions & Manual Step Waits
Enhance progress updates delivered over `/api/auth/verify-stream` SSE:

```python
# In verify_credentials progress updates:
progress_payload = {
    "step": step,
    "step_index": step_index,
    "screenshot": shot,
    "url": getattr(self, "_current_url", page.url if page else ""),
    "network_pending": len([p for p in context.pages if p.is_closed() == False])
}
```

### D. Child Auto-Discovery (`discover_children`)
Trace Angular CDK overlay clicks and new tab creations:

```python
self.log_structured(
    level="INFO",
    category="CHILD_DISCOVERY",
    message=f"Processing Actions dropdown card #{idx + 1} for '{card_name}'",
    details={"card_name": card_name}
)
with context.expect_page() as new_page_info:
    mbd.evaluate("(el) => (el.closest('a') || el.closest('button') || el).click()")

new_page = new_page_info.value
self.log_structured(
    level="DEBUG",
    category="CHILD_DISCOVERY",
    message=f"Opened child SSO tab: {new_page.url}",
    details={"tab_url": new_page.url}
)
```

### E. Media Download Requests (`extract_child_feed`)
Log every media fetch attempt with exact status codes, content types, and signed URL resolutions:

```python
self.log_structured(
    level="INFO",
    category="MEDIA_FETCH",
    message=f"Fetching media obj_id {obj_id[:8]}... (url: {download_url})",
    details={"obj_id": obj_id, "is_video": is_video, "download_url": download_url}
)

response = page.request.get(download_url, timeout=120000)
self.log_structured(
    level="INFO" if response.status == 200 else "WARN",
    category="MEDIA_FETCH_RESP",
    message=f"Media fetch response for {obj_id[:8]}: HTTP {response.status}",
    details={
        "obj_id": obj_id,
        "status": response.status,
        "content_type": response.headers.get("content-type"),
        "content_length": response.headers.get("content-length")
    }
)
```

---

## 5. Verification Method

To verify these implementation code changes once executed in Milestone 1:

1. **Unit & Integration Test Verification**:
   Execute `pytest backend/tests/` to verify backend routes and scraper job logic remain fully functional.
2. **Network Tracing & Log Output Verification**:
   Run a diagnostic verification script (e.g. `scratch/test_net_diag.py` or `demo_scrape_byron.py`) and confirm that:
   - `NETWORK_REQ`, `NETWORK_RESP`, `TURNSTILE`, `AUTH_STAGE`, `CHILD_DISCOVERY`, and `MEDIA_FETCH` entries appear in `ScraperJob.status["logs"]`.
   - Sensitive authorization headers and passwords remain masked (`[REDACTED]`).
   - HTTP response status codes (200, 302, 401, 403) are recorded with timestamp precision.

---

## Conclusion & Recommended Next Step

The current codebase lacks Playwright network event tracing and structured logging, making authentication redirects, Turnstile challenge states, and media fetch failures difficult to diagnose. 

**Recommended Action**:
Proceed to Milestone 1 Implementation, applying `NetworkTraceLogger` and structured logging methods to `backend/scraper_engine.py` and `backend/server.py` as detailed in Section 3 and 4 of this report.
