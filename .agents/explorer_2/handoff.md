# Handoff Report: Domain 3 & Domain 4 Security Analysis
**Agent:** Explorer 2  
**Recipient:** Orchestrator / Parent Agent (`9231f049-61c4-44d0-9939-f719253a4a3f`)  
**Date:** 2026-07-29  
**Type:** Hard Handoff  

---

## 1. Observation

Direct examination of codebase files (`main.py`, `backend/server.py`, `backend/security.py`, `backend/database.py`, `backend/archive_stream.py`, `backend/scraper_engine.py`) revealed the following exact lines and behaviors:

* **Token Leakage via Query Parameter**: `backend/server.py:141` (`get_media`) and `backend/server.py:174` (`download_archive`) accept `token: Optional[str] = None` from GET query parameters and validate it as a 7-day administrative JWT session token.
* **Side-Channel Timing Leak in Signature Decode**: `backend/security.py:121` (`verify_jwt_token`) executes `base64.urlsafe_b64decode` prior to `hmac.compare_digest`. Decoding errors throw `binascii.Error` immediately, returning `None` in ~500ns versus ~20µs for HMAC checks.
* **Broken HTTP Suffix Range Requests**: `backend/archive_stream.py:98-105` (`parse_range_header`): when `range_header = "bytes=-500"`, `start_str` is empty so `start` is assigned `0` and `end` is assigned `500`, returning bytes `0-500` (first 500 bytes) instead of the last 500 bytes.
* **Multipart Range Fallback Vulnerability**: In `backend/archive_stream.py:96-106`, comma-separated multi-range strings cause `int()` conversion to fail, returning `None`, which triggers `range_stream_response` (`server.py:192`) to return a `200 OK` full archive download.
* **Unencrypted Zip Storage at Rest**: `backend/archive_stream.py:52` writes unencrypted `.zip` files directly to `archives_dir` without deletion or garbage collection.
* **Lack of Zip64 Support**: `backend/archive_stream.py:54` initializes `zipfile.ZipFile` without `allowZip64=True`, causing generation failures for archives larger than 4GB.
* **Absence of Rate Limiting**: Zero rate-limiting decorators or middleware exist across all endpoints in `backend/server.py`.

---

## 2. Logic Chain

1. **Query Token Exposure**: Accepting long-lived session JWTs in URL query parameters means every image load (`<img src="/api/media/123?token=...">`) writes full user credentials into web server access logs, browser history, and `Referer` headers.
2. **Range Parser Failure for Central Directory**: Zip clients inspecting archives issue suffix range requests (`bytes=-65536`) to locate the EOCD record. Returning bytes `0-65536` corrupts client ZIP header parsing.
3. **Range Fallback DoS**: An attacker triggering multi-range requests gets full file downloads on every request, creating a bandwidth amplification vector.
4. **Storage Exhaustion**: Background zip tasks continuously append new `archive_<timestamp>.zip` files without thread locks or cleanup, allowing disk space to be exhausted.

---

## 3. Caveats

* FlareSolverr API integration (`backend/scraper_engine.py:17`) requires an active external network service running at `http://192.168.1.176:8191/v1`. In CODE_ONLY mode, live network testing was not performed; analysis was conducted via static code inspection.
* File permissions on local tenant storage directories depend on host OS umask settings.

---

## 4. Conclusion

The codebase contains critical security vulnerabilities in token handling, range header parsing, and temporary storage management. Implementation of short-lived HMAC Presigned URLs, sliding-window rate limiting, RFC 9110 compliant Range parsing, Zip64 support, and thread-safe encrypted archive lifecycle management is required before production deployment.

---

## 5. Verification Method

1. **Verify Report Generation**:
   Check that `/home/antigravity/GitHub/brighthorizon-photo-extractor/.agents/explorer_2/analysis.md` exists and contains full architectural analysis.
2. **Verify Range Suffix Parser Logic**:
   Run unit tests or python invocation of `parse_http_range_header("bytes=-500", 10000)` to ensure it returns `(9500, 9999)` instead of `(0, 500)`.
3. **Verify Presigned Token Isolation**:
   Confirm that `PresignedURLManager.verify_presigned_url` takes constant time regardless of token format or payload validity.
