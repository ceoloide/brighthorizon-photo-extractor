# ADVERSARIAL SECURITY ANALYSIS REPORT
**Target System**: Bright Horizons Photo Extractor (Multi-Tenant Architecture)  
**Author**: Explorer Subagent (`explorer_1`)  
**Date**: July 29, 2026  
**Status**: Read-Only Analysis Complete  

---

## 1. Executive Summary & Risk Matrix

An in-depth adversarial security review was performed on the Bright Horizons Photo Extractor codebase (`backend/server.py`, `backend/security.py`, `backend/database.py`, `backend/scraper_engine.py`, `backend/archive_stream.py`, and `main.py`).

The project aims to provide a multi-tenant web application and REST API for extracting, storing, and serving private photos and videos of children from the Bright Horizons parent portal.

### Summary of Critical Findings
1. **Unauthenticated Identity Takeover & Authentication Bypass**: The `/api/auth/login` endpoint does not authenticate credentials against Bright Horizons or verify existing passwords. Any unauthenticated client can post an email address with an arbitrary password, which overwrites the stored tenant credentials and issues a valid JWT token signed by the server.
2. **Unencrypted Child Media at Rest**: Media files are saved to disk with a `.dat` extension (`media/{uuid}.dat`), but their content is stored in raw, unencrypted binary format. Security relies entirely on path obfuscation.
3. **Absence of Envelope Encryption & Tenant Key Separation**: All tenant configurations and manifests are encrypted using a single static server-wide AES key (`_AES_KEY`). There is no tenant-specific data encryption key (DEK) or key management service (KMS).
4. **Missing Associated Authenticated Data (AAD)**: AES-256-GCM is invoked without AAD (`aad=None`). An attacker with local filesystem access can swap encrypted payload files (e.g., `config.enc`) across tenant directories without triggering decryption integrity failures.
5. **Cryptographic Key Separation Violation**: The symmetric AES-256 encryption key (`_AES_KEY`) is reused directly as the HMAC key for signing JWT tokens.
6. **Path Traversal Risks**: File retrieving and archive streaming endpoints resolve paths without validating that target files remain within the canonical boundary of the tenant's directory.
7. **Bearer Token Leakage via URL Query Parameters**: Sensitive JWT tokens are passed in URI query parameters for `/api/media/{id}?token=...` and `/api/archive/download?token=...`, exposing session tokens to access logs and referrers.

| Finding ID | Severity | Category | Description |
|---|---|---|---|
| **VULN-01** | **CRITICAL** | Auth & Access Control | `/api/auth/login` permits unauthenticated password overwrite and tenant token issuance |
| **VULN-02** | **CRITICAL** | Encryption at Rest | Media files stored unencrypted in raw binary (`.dat` obfuscation only) |
| **VULN-03** | **HIGH** | Encryption Architecture | Absence of Envelope Encryption; single global key shared across all tenants |
| **VULN-04** | **HIGH** | Cryptography | Missing AAD in AES-GCM allows cross-tenant ciphertext transposition attacks |
| **VULN-05** | **HIGH** | Cryptography | Cryptographic Key Reuse (`_AES_KEY` used for both AES-GCM and JWT HMAC) |
| **VULN-06** | **MEDIUM** | Input Validation | Potential path traversal in media/archive file path resolution |
| **VULN-07** | **MEDIUM** | Information Disclosure | Bearer tokens exposed in URI query parameters for media and archive streaming |
| **VULN-08** | **LOW / INFO**| Concurrency | In-memory job state (`_active_jobs`) lacks thread locking & persistent session state |

---

## 2. Domain 1: Multi-Tenant Isolation & Access Control Analysis

### Vulnerability 1.1: Unauthenticated Login & Password Overwrite (Identity Takeover)
- **File**: `backend/server.py`, Lines 59–78
- **Evidence**:
  ```python
  @app.post("/api/auth/login")
  def login(req: LoginRequest):
      email = req.email.strip().lower()
      if not email or not req.password:
          raise HTTPException(status_code=400, detail="Email and password are required")
          
      tenant_storage = TenantStorage(email)
      config = tenant_storage.load_config()
      config["email"] = email
      config["password"] = req.password # Note: config encrypted at rest via AES-256-GCM
      tenant_storage.save_config(config)
      
      token = create_jwt_token(email, tenant_storage.tenant_id)
      return {
          "status": "success",
          "token": token,
          "email": email,
          "tenant_id": tenant_storage.tenant_id,
          "children": config.get("children", [])
      }
  ```
- **Logic Chain**:
  1. An attacker sends a HTTP POST request to `/api/auth/login` with `{"email": "victim@example.com", "password": "attacker_chosen_password"}`.
  2. `TenantStorage("victim@example.com")` resolves `tenant_id = sha256("victim@example.com")`.
  3. The handler loads the existing config for `victim@example.com`, overwrites `config["password"]` with `"attacker_chosen_password"`, and saves the modified config back to disk.
  4. `create_jwt_token("victim@example.com", tenant_id)` generates a valid JWT signed by the server's master key.
  5. The attacker receives the JWT token and can now execute any endpoint (`/api/media`, `/api/extraction/start`, `/api/archive/download`) as `victim@example.com`.
- **Impact**: Total authentication bypass and identity takeover of any tenant.

### Vulnerability 1.2: Path Traversal & Unbounded Media / Archive Access
- **Files**: `backend/database.py` (Line 120), `backend/archive_stream.py` (Lines 58, 191)
- **Evidence**:
  - `database.py`:
    ```python
    abs_path = os.path.join(self.tenant_dir, item["storage_path"])
    ```
  - `archive_stream.py`:
    ```python
    abs_src = os.path.join(tenant_storage.tenant_dir, rel_path)
    zf.write(abs_src, arcname=arcname)
    ```
- **Logic Chain**:
  1. The `manifest.enc` dictionary stores `"storage_path": rel_storage_path`.
  2. When retrieving media (`get_media_file_path`) or assembling a zip archive (`start_zip_task`), `os.path.join` concatenates `self.tenant_dir` with `item["storage_path"]`.
  3. If a manifest entry is corrupted or manipulated (e.g. `storage_path = "../../../etc/passwd"`), `os.path.join` resolves outside `self.tenant_dir`.
  4. Neither `get_media_file_path` nor `start_zip_task` asserts `os.path.commonpath([abs_path, self.tenant_dir]) == self.tenant_dir`.
- **Impact**: Potential arbitrary file read from the host server filesystem.

### Vulnerability 1.3: Sensitive Token Exposure in Query Parameters
- **File**: `backend/server.py`, Lines 140–143, 173–176
- **Evidence**:
  ```python
  @app.get("/api/media/{media_id}")
  def get_media(media_id: str, token: Optional[str] = None, authorization: Optional[str] = Header(None)):
      auth_token = token
      if not auth_token and authorization and authorization.startswith("Bearer "):
          auth_token = authorization.split(" ")[1]
  ```
- **Logic Chain**:
  1. To allow HTML `<img>` tags to request protected images, the server allows passing `?token=JWT_STRING` in the URL query string.
  2. URLs containing query parameters are captured in browser history, proxy logs (Nginx/Apache), web application firewall logs, and HTTP `Referer` headers when clicking external links.
- **Impact**: Credential/session leakage via server access logs and browser histories.

### Vulnerability 1.4: Race Conditions & Concurrency Risks in Scraper Jobs
- **Files**: `backend/server.py` (Line 27, 95–113), `backend/scraper_engine.py` (Line 73)
- **Evidence**:
  ```python
  _active_jobs: Dict[str, ScraperJob] = {}
  ```
  `start_extraction` checks `if tenant_id in _active_jobs` without holding a thread mutex lock. If two concurrent requests arrive simultaneously, two background threads will be launched targeting the same `user_data_dir`. As detailed in `AGENTS.md`, Chromium persistent contexts enforce singleton locks, causing one thread to crash with `TargetClosedError`.

---

## 3. Domain 2: Encryption Scheme at Rest & Cryptographic Audit

### Vulnerability 2.1: Plaintext Media Files at Rest (Obfuscation Only)
- **File**: `backend/database.py`, Lines 86–90
- **Evidence**:
  ```python
  media_id = str(uuid.uuid4())
  rel_storage_path = os.path.join("media", f"{media_id}.dat")
  abs_storage_path = os.path.join(self.tenant_dir, rel_storage_path)
  
  with open(abs_storage_path, "wb") as f:
      f.write(file_bytes)
  ```
- **Logic Chain**:
  1. When media is downloaded from Bright Horizons, `file_bytes` are written directly to disk at `media/{uuid}.dat`.
  2. The file is saved without any encryption algorithm being applied (AES-GCM is only used for `config.enc` and `manifest.enc`).
  3. Changing a file extension to `.dat` provides zero confidentiality. Any server operator, backup administrator, or intruder gaining disk or container volume access can view all downloaded child photos and videos by executing `mv photo.dat photo.jpg`.
- **Impact**: High-severity privacy failure; sensitive photos/videos of children stored unencrypted at rest.

### Vulnerability 2.2: Absence of Envelope Encryption & Single Key Multi-Tenant Collapse
- **File**: `backend/security.py`, Lines 44–56
- **Evidence**:
  ```python
  def derive_aes_key(secret: bytes, salt: bytes) -> bytes:
      kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=600000)
      return kdf.derive(secret)

  _SALT = get_or_create_salt()
  _MASTER_SECRET = get_or_create_master_secret()
  _AES_KEY = derive_aes_key(_MASTER_SECRET, _SALT)
  ```
- **Logic Chain**:
  1. At module initialization, `_AES_KEY` is derived once from `master_secret.bin` (or `APP_SECRET` env var) and `salt.bin`.
  2. Every tenant's `config.enc` and `manifest.enc` are encrypted using this single global key `_AES_KEY`.
  3. There are no per-tenant Data Encryption Keys (DEKs), nor is there a Key Encryption Key (KEK) / Envelope Encryption mechanism.
  4. If `master_secret.bin` and `salt.bin` are compromised, every tenant's stored password and metadata across the entire database are decrypted simultaneously.
- **Impact**: Cryptographic failure; lack of cryptographic isolation between tenants.

### Vulnerability 2.3: Missing Associated Authenticated Data (AAD) and Ciphertext Transposition
- **File**: `backend/security.py`, Lines 58–71
- **Evidence**:
  ```python
  def encrypt_bytes(data: bytes) -> str:
      aesgcm = AESGCM(_AES_KEY)
      nonce = os.urandom(12)
      ciphertext = aesgcm.encrypt(nonce, data, None) # AAD is None!
      return base64.b64encode(nonce + ciphertext).decode("utf-8")
  ```
- **Logic Chain**:
  1. AES-256-GCM is an Authenticated Encryption with Associated Data (AEAD) cipher.
  2. By passing `None` as the third parameter (`associated_data`), the ciphertext tag guarantees payload integrity but does NOT bind the ciphertext to its context (e.g. `tenant_id` or `file_type`).
  3. An attacker with filesystem access to Tenant A's `config.enc` can copy Tenant A's `config.enc` into Tenant B's folder (`/data/tenants/{tenant_B_id}/config.enc`).
  4. When Tenant B accesses the application, `decrypt_json` succeeds without error because `_AES_KEY` is identical and no AAD bound the ciphertext to Tenant A's `tenant_id`.
- **Impact**: Ciphertext transposition/swap attacks across tenants.

### Vulnerability 2.4: Cryptographic Key Reuse (AES-GCM Encryption Key Used for JWT HMAC)
- **File**: `backend/security.py`, Lines 102, 116
- **Evidence**:
  ```python
  signature = hmac.new(_AES_KEY, signature_input, hashlib.sha256).digest()
  ```
- **Logic Chain**:
  1. `_AES_KEY` is derived as a 256-bit symmetric key for AES-GCM data encryption.
  2. `create_jwt_token` and `verify_jwt_token` use `_AES_KEY` as the HMAC key to sign and verify JWT authentication tokens.
  3. Cryptographic best practices (NIST SP 800-57) strictly prohibit using the same key material across different cryptographic algorithms or protocols (AEAD encryption vs HMAC signing).
- **Impact**: Structural key reuse violation; potential cross-protocol key leakage vulnerabilities.

### Vulnerability 2.5: Key Derivation Function (PBKDF2 vs Argon2id)
- **File**: `backend/security.py`, Lines 44–52
- **Evidence**: `PBKDF2HMAC` with SHA256 and 600,000 iterations is used.
- **Evaluation**: While 600,000 iterations meets older recommendations, PBKDF2 is CPU-bound and lacks memory-hardness. Modern password/key derivation standards (OWASP 2026 / RFC 9106) recommend **Argon2id** (with parameters $m=64\text{MB}, t=3, p=4$) to mitigate GPU/ASIC-assisted brute-force key cracking.

---

## 4. Architectural Recommendations & Remediation Blueprints

### Blueprint A: Envelope Encryption Architecture (KMS / Master Key + Tenant DEKs + AAD)

```
                       +-----------------------------------+
                       | Master Key (KMS / APP_SECRET)    |
                       +-----------------------------------+
                                         |
                                         v
                       +-----------------------------------+
                       | Key Derivation (Argon2id)         |
                       +-----------------------------------+
                                         |
                                         v
                       +-----------------------------------+
                       | Master Key Encryption Key (KEK)   |
                       +-----------------------------------+
                                         |
                 +-----------------------+-----------------------+
                 | (Encrypted with KEK)                          | (Encrypted with KEK)
                 v                                               v
    +--------------------------+                   +--------------------------+
    | Tenant A Encrypted DEK   |                   | Tenant B Encrypted DEK   |
    +--------------------------+                   +--------------------------+
                 |                                               |
                 v (Decrypted DEK_A)                             v (Decrypted DEK_B)
    +--------------------------+                   +--------------------------+
    | AES-256-GCM Payload      |                   | AES-256-GCM Payload      |
    | AAD: tenant_id_A         |                   | AAD: tenant_id_B         |
    +--------------------------+                   +--------------------------+
```

### Blueprint B: Remediation Pseudocode

#### 1. Secure Cryptographic Module (`backend/security.py`)

```python
import os
import base64
import json
import hashlib
import hmac
import time
from typing import Dict, Any, Optional, Tuple
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

DATA_DIR = os.environ.get("DATA_DIR", "/data")

def derive_master_kek(secret: bytes, salt: bytes) -> bytes:
    """Derives a 256-bit Master Key Encryption Key (KEK) using Argon2id."""
    kdf = Argon2id(
        salt=salt,
        length=32,
        iterations=3,
        memory_cost=65536, # 64 MB
        lanes=4
    )
    return kdf.derive(secret)

def derive_jwt_signing_key(secret: bytes, salt: bytes) -> bytes:
    """Derives a dedicated key for HMAC JWT signing, maintaining strict key separation."""
    h = hmac.new(secret, b"JWT_SIGNING_KEY_CONTEXT" + salt, hashlib.sha256)
    return h.digest()

# Initialize separate derived keys
_SALT = get_or_create_salt()
_MASTER_SECRET = get_or_create_master_secret()
_MASTER_KEK = derive_master_kek(_MASTER_SECRET, _SALT)
_JWT_SIGNING_KEY = derive_jwt_signing_key(_MASTER_SECRET, _SALT)

def generate_tenant_dek() -> bytes:
    """Generates a random 256-bit Data Encryption Key (DEK) for a tenant."""
    return AESGCM.generate_key(bit_length=256)

def encrypt_tenant_dek(dek: bytes, tenant_id: str) -> str:
    """Encrypts tenant DEK using Master KEK with tenant_id bound as AAD."""
    aesgcm = AESGCM(_MASTER_KEK)
    nonce = os.urandom(12)
    aad = f"tenant_dek:{tenant_id}".encode("utf-8")
    ciphertext = aesgcm.encrypt(nonce, dek, aad)
    return base64.b64encode(nonce + ciphertext).decode("utf-8")

def decrypt_tenant_dek(encrypted_dek_b64: str, tenant_id: str) -> bytes:
    """Decrypts tenant DEK using Master KEK and validates tenant_id AAD."""
    raw = base64.b64decode(encrypted_dek_b64.encode("utf-8"))
    nonce, ciphertext = raw[:12], raw[12:]
    aesgcm = AESGCM(_MASTER_KEK)
    aad = f"tenant_dek:{tenant_id}".encode("utf-8")
    return aesgcm.decrypt(nonce, ciphertext, aad)

def encrypt_tenant_payload(data: bytes, dek: bytes, tenant_id: str, context: str) -> str:
    """Encrypts arbitrary bytes using tenant DEK with tenant_id and context bound in AAD."""
    aesgcm = AESGCM(dek)
    nonce = os.urandom(12)
    aad = f"tenant:{tenant_id}:context:{context}".encode("utf-8")
    ciphertext = aesgcm.encrypt(nonce, data, aad)
    return base64.b64encode(nonce + ciphertext).decode("utf-8")

def decrypt_tenant_payload(encrypted_b64: str, dek: bytes, tenant_id: str, context: str) -> bytes:
    """Decrypts tenant payload using tenant DEK and validates AAD context."""
    raw = base64.b64decode(encrypted_b64.encode("utf-8"))
    nonce, ciphertext = raw[:12], raw[12:]
    aesgcm = AESGCM(dek)
    aad = f"tenant:{tenant_id}:context:{context}".encode("utf-8")
    return aesgcm.decrypt(nonce, ciphertext, aad)
```

#### 2. Encrypted Media Storage Stream Handler (`backend/database.py`)

```python
def save_media_file_encrypted(self, media_id: str, file_bytes: bytes) -> str:
    """Encrypts media file bytes at rest using tenant DEK before writing to disk."""
    dek = self.get_or_create_tenant_dek()
    rel_path = os.path.join("media", f"{media_id}.enc")
    abs_path = os.path.join(self.tenant_dir, rel_path)
    
    # Encrypt file bytes with media_id bound to AAD
    encrypted_b64 = encrypt_tenant_payload(file_bytes, dek, self.tenant_id, context=f"media:{media_id}")
    with open(abs_path, "w") as f:
        f.write(encrypted_b64)
    return rel_path

def read_media_file_decrypted(self, media_id: str, rel_path: str) -> bytes:
    """Reads and decrypts media file bytes from disk."""
    abs_path = os.path.join(self.tenant_dir, rel_path)
    # Assert canonical path security
    if not os.path.realpath(abs_path).startswith(os.path.realpath(self.tenant_dir)):
        raise PermissionError("Path traversal attack detected")
        
    dek = self.get_or_create_tenant_dek()
    with open(abs_path, "r") as f:
        encrypted_b64 = f.read()
    return decrypt_tenant_payload(encrypted_b64, dek, self.tenant_id, context=f"media:{media_id}")
```

#### 3. Corrected Authentication Endpoint (`backend/server.py`)

```python
@app.post("/api/auth/login")
def login(req: LoginRequest):
    email = req.email.strip().lower()
    if not email or not req.password:
        raise HTTPException(status_code=400, detail="Email and password are required")
        
    tenant_storage = TenantStorage(email)
    
    # Check if tenant already has an established configuration
    if tenant_storage.has_config():
        existing_config = tenant_storage.load_config()
        # Verify supplied password matches existing tenant password
        if existing_config.get("password") and existing_config["password"] != req.password:
            raise HTTPException(status_code=401, detail="Invalid tenant credentials")
            
    # Save/Update credentials
    config = tenant_storage.load_config()
    config["email"] = email
    config["password"] = req.password
    tenant_storage.save_config(config)
    
    token = create_jwt_token(email, tenant_storage.tenant_id)
    return {
        "status": "success",
        "token": token,
        "email": email,
        "tenant_id": tenant_storage.tenant_id,
        "children": config.get("children", [])
    }
```

---

## 5. Verification Method

To independently verify these security findings and subsequent remediation implementations:

1. **Verify VULN-01 (Auth Bypass)**:
   - Run `pytest backend/tests/test_security.py`.
   - Send an HTTP POST to `/api/auth/login` targeting an existing tenant email with a fake password. Observe that the endpoint returns `200 OK` with a valid JWT and overwrites `config.enc`.

2. **Verify VULN-02 (Unencrypted Media)**:
   - Inspect files under `/data/tenants/{tenant_id}/media/*.dat`.
   - Run `file /data/tenants/{tenant_id}/media/*.dat`. Observe output `JPEG image data` or `PNG image data` directly.

3. **Verify VULN-04 (Ciphertext Transposition)**:
   - Copy `config.enc` from `/data/tenants/{tenant_A_id}/` to `/data/tenants/{tenant_B_id}/`.
   - Invoke `TenantStorage("userB@example.com").load_config()`. Observe that decryption succeeds without raising a cryptographic validation error.

---
*End of Security Analysis Report.*
