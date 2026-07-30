# Comprehensive Adversarial Security Review & Architectural Specification
## Project: Multi-Tenant Bright Horizons Photo Extractor
**Date**: July 29, 2026  
**Status**: Completed  
**Target Architecture**: Multi-Tenant Bright Horizons Media Extractor (`main.py`, `PROMPT.md`)

---

## Executive Summary

This document presents a rigorous, adversarial security evaluation and architectural specification for transitioning the Bright Horizons photo extractor from a single-tenant CLI utility into a secure, multi-tenant cloud service. 

Our assessment evaluated five critical security and architectural domains:
1. **Multi-Tenant Isolation & Access Control**
2. **Encryption Scheme at Rest & Envelope Cryptography**
3. **Anti-Enumeration, Oracle Protection & Timing Side-Channels**
4. **Resumable ZIP Archive Downloads via HTTP Range Headers (206 Partial Content)**
5. **Headless Cloudflare Bypass, Stealth Evasion & Session Management**

---

## Domain 1: Multi-Tenant Isolation & Access Control

### 1.1 Vulnerability & Attack Vector Analysis

#### A. Database Row-Level Security (RLS) & Connection Pooling Leakage
- **The Pitfall**: Utilizing PostgreSQL Row-Level Security (`ALTER TABLE media ENABLE ROW LEVEL SECURITY;`) using session variables like `SET LOCAL app.current_tenant_id = 'tenant_123';`.
- **Attack Vector**: When using high-performance connection poolers (such as PgBouncer in `transaction` mode or SQLAlchemy connection pooling), connections are reused across different HTTP requests. If a worker thread fails to reset or set `app.current_tenant_id` on a checked-out connection (e.g., due to an unhandled exception or early return), subsequent queries executed by Tenant B will run under Tenant A's context, leading to catastrophic cross-tenant data leakage.
- **RLS Join Bypass**: RLS policies placed on a child table (e.g., `media`) but omitted from parent tables (e.g., `children` or `timeframes`) allow an attacker to infer metadata or enumerate media counts across tenants via relational subqueries.

#### B. Tenant-Scoped Storage Paths & Path Traversal (IDOR)
- **The Pitfall**: Storing tenant assets using raw user-provided or scraped parameters (e.g., `s3://bucket/{tenant_id}/{child_name}/{filename}`).
- **Attack Vector**: In `main.py:945`, `child_name` is extracted from the web portal DOM. If a user sets a child's name or nickname to `../../tenant_victim/media`, or if a malicious payload is injected into `post_date` or `obj_id`, `os.path.join` or S3 path construction resolves outside the tenant's isolated directory prefix.
- **Storage IAM Flaw**: Granting the application worker a broad S3 `GetObject` IAM policy across `s3://bucket/*`. A compromised worker thread for Tenant A can request `s3://bucket/tenant_B/secret.jpg` directly.

#### C. Session Isolation & Context Leakage in Async Runtimes
- **The Pitfall**: Storing context (such as tenant ID, user session, or HTTP client) in global variables or thread-local storage in Python `asyncio` runtimes.
- **Attack Vector**: In Python `asyncio`, thread-local variables are shared across all coroutines executing on the same thread event loop. Relying on `threading.local()` rather than `contextvars.ContextVar` causes coroutine context switching to bleed Tenant A's credentials into Tenant B's request handler.

---

### 1.2 Concrete Architectural Specification & Mitigation

```
                           +-----------------------------------+
                           |    API Gateway / OAuth Layer      |
                           +-----------------------------------+
                                             |
                                  Validates Tenant JWT
                                             |
                                             v
                           +-----------------------------------+
                           |  Application Worker ContextVar    |
                           |  (tenant_id bound to Coroutine)   |
                           +-----------------------------------+
                                     /               \
                                    /                 \
                                   v                   v
+---------------------------------------+   +---------------------------------------+
|  PostgreSQL RLS with Explicit Query   |   |   Scoped Storage Client (AWS STS)     |
|  AND Tenant Predicates                |   |   Policy: s3://bucket/tenants/${tenant}   |
+---------------------------------------+   +---------------------------------------+
```

#### 1. Database Row-Level Security (PostgreSQL)
Always pair RLS with explicit query-level filtering. Do not rely solely on session state.

```sql
-- Schema Setup
CREATE TABLE tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT clock_timestamp()
);

CREATE TABLE media (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    child_id UUID NOT NULL,
    storage_key TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT clock_timestamp()
);

-- Enable RLS
ALTER TABLE media ENABLE ROW LEVEL SECURITY;
ALTER TABLE media FORCE ROW LEVEL SECURITY;

-- Strict Tenant Policy using Session Variable
CREATE POLICY media_tenant_isolation_policy ON media
    FOR ALL
    USING (tenant_id = NULLIF(current_setting('app.current_tenant_id', true), '')::uuid);
```

#### 2. Safe Tenant Storage Path Canonicalization (Python)
```python
import os
import re

def get_tenant_storage_key(tenant_id: str, child_name: str, filename: str) -> str:
    # Strict UUID validation for tenant_id
    if not re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$', tenant_id, re.I):
        raise ValueError("Invalid tenant_id format")
    
    # Sanitize child_name and filename to alphanumeric + strict chars
    safe_child = re.sub(r'[^\w\-. ]', '_', child_name).strip('.')
    safe_filename = re.sub(r'[^\w\-. ]', '_', filename).strip('.')
    
    base_prefix = f"tenants/{tenant_id}/media/"
    target_key = f"{base_prefix}{safe_child}/{safe_filename}"
    
    # Canonical path boundary verification
    normalized = os.path.normpath(target_key)
    if not normalized.startswith(base_prefix):
        raise SecurityError("Path traversal attempt detected in tenant storage key generation")
        
    return normalized
```

---

## Domain 2: Encryption Scheme at Rest & Envelope Cryptography

### 2.1 Cryptographic Flaws & Threat Vectors

#### A. Database Dumps & Server Operator Threat Model
- If an attacker steals a database dump or gains read access to the local storage disk, storing raw media or plain text session credentials (e.g. Bright Horizons password / OAuth cookies) compromises all users.
- Storing a static encryption key in `.env` or application config allows anyone with read access to server process environment variables (`/proc/self/environ`) to decrypt all tenant data.

#### B. AES-GCM Nonce / IV Reuse & Counter Overflow
- **AES-256-GCM** requires a 96-bit (12-byte) initialization vector (IV).
- **Catastrophic Failure**: If the same key encrypts two different plaintexts ($P_1, P_2$) using the same IV ($IV$), the XOR of the plaintexts is revealed directly in the XOR of the ciphertexts ($C_1 \oplus C_2 = P_1 \oplus P_2$). Furthermore, IV reuse allows an attacker to recover the GHASH authentication key, destroying both confidentiality and authenticity.
- **Random IV Limits**: Using random 96-bit IVs with a static key introduces collision risks due to the Birthday Paradox after $2^{32}$ encryptions (~4 billion blocks).

#### C. Ciphertext Transposition / Swap Attacks Across Tenants
- **The Vector**: An attacker with read/write access to DB ciphertexts (or via SQL Injection) swaps Tenant A's encrypted media record with Tenant B's encrypted media record.
- **The Exploit**: If the decryption routine decrypts ciphertext using Tenant B's key without verifying data context, Tenant B sees Tenant A's decrypted photo.
- **Mitigation**: Associated Authenticated Data (AAD) **must** bind `tenant_id` and `record_id` to the GCM tag calculation!

---

### 2.2 Concrete Envelope Encryption Specification

```
                               +-----------------------------+
                               |   Cloud KMS / Master Key    |
                               |  (AWS KMS / GCP Cloud KMS)  |
                               +-----------------------------+
                                              |
                                   Decrypts Tenant EDEK
                                              |
                                              v
+------------------------+     +-----------------------------+     +-------------------------+
|  Encrypted Data Key    | --> | AES-256-GCM Decryption      | --> |  Plaintext Credentials  |
|  (EDEK in DB)          |     | AAD: tenant_id | record_id  |     |  or Media File          |
+------------------------+     +-----------------------------+     +-------------------------+
                                              ^
                                              |
                               +-----------------------------+
                               | Unique 96-bit CSPRNG Nonce  |
                               +-----------------------------+
```

#### Cryptographic Architecture Rules:
1. **Master Key (KMS)**: Stored in AWS KMS / GCP KMS / HashiCorp Vault. Never leaves HSM.
2. **Per-Tenant Data Encryption Key (DEK)**: Generated via KMS `GenerateDataKey(KeyId=MasterKeyId, KeySpec='AES_256')`. The plaintext DEK is used in memory for operations and immediately zeroed; the Encrypted DEK (EDEK) is stored in the `tenants` table.
3. **Key Derivation for User Passwords**: Argon2id (`m=64MB, t=3, p=4`) with a unique 32-byte CSPRNG salt per tenant.
4. **AES-GCM Encryption with AAD**:

```python
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class TenantEnvelopeEncryption:
    def __init__(self, raw_dek_32_bytes: bytes):
        if len(raw_dek_32_bytes) != 32:
            raise ValueError("DEK must be exactly 256 bits (32 bytes)")
        self.aesgcm = AESGCM(raw_dek_32_bytes)

    def encrypt_tenant_media(self, tenant_id: str, record_id: str, plaintext: bytes) -> dict:
        # Generate 96-bit (12-byte) unique IV from CSPRNG
        nonce = os.urandom(12)
        
        # Bind tenant_id and record_id into AAD to prevent transposition attacks
        aad = f"tenant:{tenant_id}|record:{record_id}".encode('utf-8')
        
        # Ciphertext includes the 128-bit authentication tag appended by AESGCM
        ciphertext = self.aesgcm.encrypt(nonce, plaintext, aad)
        
        return {
            "nonce": nonce.hex(),
            "ciphertext": ciphertext,
            "aad": aad.decode('utf-8')
        }

    def decrypt_tenant_media(self, tenant_id: str, record_id: str, nonce_hex: str, ciphertext: bytes) -> bytes:
        nonce = bytes.fromhex(nonce_hex)
        aad = f"tenant:{tenant_id}|record:{record_id}".encode('utf-8')
        
        try:
            # Re-authentication fails if ciphertext was modified OR transposed to another tenant/record
            plaintext = self.aesgcm.decrypt(nonce, ciphertext, aad)
            return plaintext
        except Exception as e:
            raise SecurityError("Decryption failed: Ciphertext integrity check or AAD tenant binding failed") from e
```

---

## Domain 3: Anti-Enumeration, Oracle Protection & Timing Leaks

### 3.1 Side-Channel & Timing Attack Analysis

#### A. Non-Constant-Time Token & Signature Comparisons
- Standard equality check (`if request_token == valid_token:`) terminates early at the first byte mismatch.
- **Attack Vector**: An attacker measures microsecond variations in response times over thousands of HTTP requests to reconstruct secret HMAC signatures or auth tokens byte-by-byte.

#### B. Oracle Leakage via Error Messages & Status Codes
- Returning `404 Not Found` when a file does not exist versus `403 Forbidden` when it exists but belongs to another tenant exposes an **enumeration oracle**.
- Returning detailed decryption errors (e.g. `Invalid Padding`, `Tag mismatch`, `Key missing`) exposes cryptographic verification status to attackers.

---

### 3.2 HMAC-Signed Presigned Temporary URLs & Rate Limiting

#### HMAC Presigned URL Specification
URLs must be single-use or time-bounded with signed parameter context.

```python
import hmac
import hashlib
import time
from urllib.parse import urlencode

class SecureMediaSigner:
    def __init__(self, secret_key: bytes):
        self.secret_key = secret_key

    def generate_presigned_url(self, base_url: str, tenant_id: str, media_id: str, ttl_seconds: int = 300) -> str:
        expires = int(time.time()) + ttl_seconds
        # Canonical string covers method, tenant, media_id, and expiration
        canonical_str = f"GET\n{tenant_id}\n{media_id}\n{expires}"
        
        signature = hmac.new(
            self.secret_key,
            canonical_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        params = {
            "tenant_id": tenant_id,
            "media_id": media_id,
            "expires": expires,
            "sig": signature
        }
        return f"{base_url}?{urlencode(params)}"

    def verify_presigned_url(self, tenant_id: str, media_id: str, expires: int, provided_sig: str) -> bool:
        # 1. Check expiration
        if int(time.time()) > expires:
            return False
            
        # 2. Recompute canonical string
        canonical_str = f"GET\n{tenant_id}\n{media_id}\n{expires}"
        expected_sig = hmac.new(
            self.secret_key,
            canonical_str.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        # 3. Constant-time comparison to eliminate timing side-channels
        return hmac.compare_digest(expected_sig, provided_sig)
```

#### Distributed Rate Limiting (Redis Sliding Window)
To prevent enumeration brute-forcing, enforce rate limits per tenant and IP:

```lua
-- Redis Lua script for Sliding Window Rate Limiter
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local clearBefore = now - window

redis.call('ZREMRANGEBYSCORE', key, 0, clearBefore)
local currentRequests = redis.call('ZCARD', key)

if currentRequests < limit then
    redis.call('ZADD', key, now, now)
    redis.call('EXPIRE', key, window)
    return 1
else
    return 0
end
```

---

## Domain 4: Resumable ZIP Downloads via HTTP Range Headers (206)

### 4.1 Technical Challenges & Vulnerabilities

#### A. The ZIP Central Directory Layout Problem
- **The Issue**: A ZIP archive places its **Central Directory (EOCD)** at the **end** of the file.
- When browser download managers or `curl -C -` issue Range requests (`Range: bytes=-1024` or `Range: bytes=5000-`), they attempt to read the last 1KB to parse file headers before requesting file chunks.
- **Dynamic Streaming Conflict**: Generating a ZIP archive on-the-fly via a stream does not allow satisfying arbitrary end-of-file byte ranges unless the total ZIP archive size and offsets are pre-calculated.

#### B. Multi-Range DoS & Integer Overflow Amplification
- **The Vector**: Requesting `Range: bytes=0-10, 11-20, 21-30...` with hundreds of overlapping ranges forces the server to construct complex multipart responses, exhausting CPU and memory (Range Amplification DoS).

---

### 4.2 Architectural Solution: Virtual ZIP Pre-computation & HTTP 206 Streaming

```
  Step 1: Compute Layout & Offsets       Step 2: Serve HTTP Range 206
+-----------------------------------+   +------------------------------------+
| Query Tenant Media Metadata       |   | Parse Range: bytes=start-end       |
| Calculate Local Headers + Sizes   |   | Seek into precomputed virtual stream|
| Construct Virtual EOCD Header     |   | Decrypt & Stream target slice only |
+-----------------------------------+   +------------------------------------+
```

#### Range Header Validation & Handling (Python FastAPI)

```python
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import StreamingResponse
import re

app = FastAPI()

MAX_ZIP_SIZE = 10 * 1024 * 1024 * 1024  # 10 GB limit (Zip64 required)

def parse_single_byte_range(range_header: str, total_length: int):
    if not range_header or not range_header.startswith("bytes="):
        return None
        
    # Reject multi-range requests to prevent Range Overlap DoS
    if "," in range_header:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Multiple byte ranges are not supported."
        )
        
    match = re.match(r"^bytes=(\d*)-(\d*)$", range_header.strip())
    if not match:
        raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE)
        
    start_str, end_str = match.groups()
    
    if start_str and end_str:
        start = int(start_str)
        end = int(end_str)
    elif start_str:
        start = int(start_str)
        end = total_length - 1
    elif end_str:
        start = total_length - int(end_str)
        end = total_length - 1
    else:
        return None
        
    if start > end or start >= total_length or end >= total_length:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            headers={"Content-Range": f"bytes */{total_length}"}
        )
        
    return start, end
```

---

## Domain 5: Headless Cloudflare Bypass, Stealth Evasion & Session Management

### 5.1 Cloudflare Turnstile & Bot Detection Evasion

#### Anti-Bot Fingerprinting Elements Evaluated:
1. **WebGL / Canvas Hardware Acceleration**: Standard headless Chromium (`headless=True`) utilizes SwiftShader software rendering. Cloudflare inspects WebGL vendor strings (`Google Inc. (Google SwiftShader)`). Software rendering immediately flags browser context as automated.
2. **JA3 / JA4 TLS Fingerprints**: Node.js / Python Playwright network stacks emit distinct TLS cipher suite order and extension parameters that differ from real Chrome desktop clients.
3. **HTTP/2 SETTINGS Frame**: Automated headless browsers send default HTTP/2 settings frames (such as `max_concurrent_streams`) that do not match desktop browser signatures.
4. **JS Runtime Environment**: Overriding `navigator.webdriver` via command-line flags (`--disable-blink-features=AutomationControlled`) is insufficient against Turnstile v2, which tests `window.chrome`, `navigator.plugins`, `permissions.query()`, and object prototype fidelity.

---

### 5.2 Single-Tenant Lock & Session Leakage in `main.py`

#### A. Singleton Lock Crash
- **Code Bug in `main.py:727-735`**: `user_data_dir` defaults to `./user_data`.
- Chromium places an OS-level file lock (`SingletonLock`) on `./user_data`. When multiple tenant scraper tasks run concurrently, Chromium fails to launch, raising `TargetClosedError`.

#### B. Cross-Tenant Cookie & Credential Leakage
- Storing all sessions in `./user_data` causes Tenant B to inherit Tenant A's cookies, local storage, and authentication tokens, allowing Tenant B to view Tenant A's children photos.

---

### 5.3 Architectural Recommendation: Isolated Playwright Container Worker

```
                                  +------------------------------------+
                                  |   Tenant Scraping Job Queue        |
                                  +------------------------------------+
                                                    |
                                      Dispatches isolated job payload
                                                    |
                                                    v
                                  +------------------------------------+
                                  | Ephemeral Docker Worker Container  |
                                  | - Xvfb (Virtual Framebuffer)       |
                                  | - Isolated Temporary Profile Dir   |
                                  | - Dedicated Sticky Residential IP  |
                                  +------------------------------------+
```

#### Production Multi-Tenant Browser Launcher

```python
import os
import shutil
import tempfile
from playwright.sync_api import sync_playwright

def run_isolated_tenant_scrape(tenant_id: str, proxy_url: str):
    # Allocate dedicated temporary directory for user profile
    tenant_profile_dir = tempfile.mkdtemp(prefix=f"bh_profile_{tenant_id}_")
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch_persistent_context(
                user_data_dir=tenant_profile_dir,
                headless=False,  # Executed inside Xvfb container for real GPU rendering
                proxy={"server": proxy_url} if proxy_url else None,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--window-size=1920,1080"
                ],
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            )
            
            page = browser.pages[0]
            # Inject stealth scripts to fix navigator.plugins and permissions
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = { runtime: {} };
            """)
            
            # Execute scraper logic...
            browser.close()
    finally:
        # Strict cleanup of temporary profile directory to prevent disk bloat and credential lingering
        if os.path.exists(tenant_profile_dir):
            shutil.rmtree(tenant_profile_dir, ignore_errors=True)
```

---

## Actionable Security Roadmap & Priority Summary

| Priority | Vulnerability / Requirement | Immediate Action |
| :--- | :--- | :--- |
| **P0 (Critical)** | Cross-Tenant Session & Profile Leakage | Eliminate shared `./user_data` in Playwright; allocate isolated temp profiles per tenant task. |
| **P0 (Critical)** | Path Traversal in File Saving | Wrap all input parsing (`child_name`, `post_date`) in `get_tenant_storage_key()` bounds validation. |
| **P1 (High)** | Plaintext Credential Storage | Implement AES-256-GCM envelope encryption with per-tenant DEKs and AAD binding (`tenant_id\|record_id`). |
| **P1 (High)** | Multi-Tenant Database Isolation | Configure PostgreSQL RLS and enforce explicit `tenant_id` clauses on all queries. |
| **P2 (Medium)**| Anti-Enumeration & Presigned URLs | Replace integer IDs with UUID v7; generate HMAC-SHA256 presigned URLs with expiry checks. |
| **P2 (Medium)**| Range Request DoS & ZIP Headers | Disallow multi-range headers; precompute virtual ZIP offsets for 206 Partial Content downloads. |

---
*End of Security Review Specification Report.*
