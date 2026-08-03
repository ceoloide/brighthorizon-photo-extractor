# Security & Tenant Isolation Analysis and Architecture Design

**Target File**: `backend/security_isolation.py`  
**Author**: Explorer Agent M1.2  
**Date**: 2026-07-31  

---

## 1. Executive Summary & Architectural Context

The Bright Horizons Photo Extractor is a multi-tenant backend engine that automates browser interaction via Playwright/Chromium, retrieves high-resolution photos/videos, injects custom PNG metadata, and manages encrypted data at rest per tenant.

Security and tenant isolation are core architectural imperatives for this system:
1. **Concurrency & Playwright Locks**: Simultaneous scraper jobs or diagnostic verification runs sharing Chromium profile directories (`user_data`) can fail with `TargetClosedError` due to Chromium's singleton lock files (`SingletonLock`, `SingletonCookie`, `RunningChromeVersion`, etc.).
2. **Credential & Sensitive Data Exposure**: Unsanitized logging callbacks, progress telemetry, or manifest dumps could accidentally leak user passwords, 6-digit MFA verification codes, Auth0 tokens, JWT signatures, or session cookies to stdout, web logs, or API progress endpoints.
3. **Path Traversal & Multi-Tenant Data Leakage**: Naïve string prefix checks (`abspath(path).startswith(abspath(tenant_dir))`) contain critical security vulnerabilities (e.g., prefix collision between `/data/tenants/tenant1` and `/data/tenants/tenant10`, unhandled symlinks, null byte injection, and unsanitized child folder names).

This document presents a comprehensive security analysis and complete proposed architecture for `backend/security_isolation.py` to systematically solve these vulnerabilities.

---

## 2. Deep-Dive Analysis of Focus Areas

### Focus Area 1: Playwright Persistent Profile Singleton Lock Avoidance Architecture

#### Root Cause Analysis
When Playwright launches Chromium with `launch_persistent_context(user_data_dir, ...)`, Chromium creates several lock files and Unix domain sockets inside `user_data_dir`:
- `SingletonLock`: A symbolic link pointing to `<hostname>-<pid>`.
- `SingletonCookie`: Cookie lock file.
- `SingletonSocket`: Domain socket for IPC communication between Chromium instances.
- `RunningChromeVersion`: Text file containing the active Chrome binary version.
- Other pattern locks: `*Lock*`, `*.lock`, `LOCK`, `DEVTOOLS_LOCK`.

If a background scrape job is actively running or chromium crashes ungracefully, these lock files remain. Attempting to launch a second Chromium instance against the same `user_data_dir` results in:
```
Playwright target closed error: Chromium process died or failed to acquire singleton lock.
```

#### Proposed Copy-on-Write / Ephemeral Directory Pattern
To support concurrent Playwright runs (e.g., diagnostic logins, MFA verifications, parallel syncs) without lock contention:
1. **Isolated Copy Generation**: Before launching Playwright, create a temporary isolated working directory (e.g., `user_data_isolated_<uuid>`).
2. **Pattern Exclusion during Directory Copying**:
   - System `rsync` fast-path (if available):
     ```bash
     rsync -a --delete --exclude="Singleton*" --exclude="RunningChromeVersion" --exclude="*Lock*" source_dir/ dest_dir/
     ```
   - Pure-Python fallback using `shutil.copytree` with `shutil.ignore_patterns`:
     ```python
     shutil.copytree(
         source_dir,
         dest_dir,
         ignore=shutil.ignore_patterns("Singleton*", "RunningChromeVersion", "*Lock*", "*.lock", "LOCK", "DEVTOOLS_LOCK"),
         dirs_exist_ok=True
     )
     ```
3. **In-Place Lock Purging**: A lightweight helper `clean_user_data_locks(dir)` that recursively unlinks any residual lock files from a target profile directory before launching Chromium context.
4. **Lifecycle Context Manager (`IsolatedUserDataContext`)**: Automatically manages creation, lock exclusion, execution, optional session state back-sync (`storage_state.json`), and automatic cleanup of the ephemeral directory upon exit.

---

### Focus Area 2: Credential & Sensitive Data Masking Framework

#### Vulnerability Vector
During scraper job execution, authentication, and MFA submission, diagnostic logs are generated and sent to:
- Standard output (`print`)
- Job progress state (`job.status["logs"]`)
- Websocket/SSE streaming clients via `log_callback`

Without strict regex-based redacting, sensitive credentials can leak into log files or API responses:
- Plaintext user credentials (`password="Secret123"`, `"password": "..."`)
- 6-digit MFA codes (`code="123456"`, `mfa_code="654321"`)
- Bearer tokens, Auth0 tokens, JWT tokens (`eyJ...`)
- HTTP headers containing session cookies (`AWSALB=...`, `JSESSIONID=...`)

#### Masking Engine Design
`backend/security_isolation.py` introduces a robust regular expression redactor:
1. **Password Redaction**: Matches `password`, `pass`, `pwd`, `secret` in JSON, key-value, or log string formats.
2. **MFA Code Redaction**: Matches 6-digit verification code patterns in context (`code=\d{6}`, `MFA code: \d{6}`).
3. **Token Redaction**: Matches JWT signatures (`eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+`), Authorization Bearer tokens, and Auth0 access codes.
4. **Sanitized Logger Wrapper (`SanitizedLogger`)**: Wraps any logger function to guarantee that every string passes through `mask_sensitive_data()` prior to storage or emission.
5. **Manifest & Config Sanitizer (`sanitize_manifest_metadata`)**: Strips volatile session cookies, tokens, or raw state dictionary objects before exporting manifests or logging diagnostic summaries.

---

### Focus Area 3: Path Traversal & Child Tenant Isolation Engine

#### Critical Vulnerability Analysis in Existing Code
In `backend/database.py` (lines 102–104, 117–118, 151–152), path checking is implemented as:
```python
abs_path = os.path.abspath(os.path.join(self.tenant_dir, item["storage_path"]))
if not abs_path.startswith(os.path.abspath(self.tenant_dir)):
    return None
```

This check suffers from three major security flaws:

1. **Prefix Overlap Flaw (Tenant Data Leakage)**:
   - Suppose `Tenant A` has `tenant_dir = "/data/tenants/tenant1"`.
   - Suppose `Tenant B` has `tenant_dir = "/data/tenants/tenant10"`.
   - `os.path.abspath(self.tenant_dir)` for Tenant A is `"/data/tenants/tenant1"`.
   - If Tenant A attempts to access `/data/tenants/tenant10/media/secret.dat`, `startswith("/data/tenants/tenant1")` evaluates to **`True`** because `"/data/tenants/tenant10..."` starts with `"/data/tenants/tenant1"`!
   - **Exploit impact**: Tenant 1 can read or overwrite files belonging to Tenant 10.

2. **Symlink Escape Vulnerability**:
   - `os.path.abspath()` does NOT resolve symlinks. If a file inside `tenant_dir` is a symlink pointing to `/etc/passwd` or `/data/tenants/tenant2/`, `os.path.abspath()` returns the symlink path inside `tenant_dir`, passing the `startswith` check while allowing unauthorized file access.
   - **Fix**: Must use `os.path.realpath()`.

3. **Unsanitized Child Directory Names**:
   - Child names obtained from Knockout JS UI elements or API options (e.g. `Byron`, `Catherine`) might be manipulated or contain characters like `../`, `/`, `\`, or null bytes (`\x00`).
   - Saving media under `media/<child>/filename.jpg` without child name sanitization can lead to path traversal outside the tenant's media directory.

#### Path Isolation Solution
`security_isolation.py` introduces canonical path validation:
- **`canonicalize_and_validate_path(base_dir, target_path)`**:
  1. Checks for null bytes (`\x00`).
  2. Resolves real paths using `os.path.realpath()`.
  3. Ensures trailing separator on base directory (`os.path.join(real_base, "")`) or uses `os.path.commonpath([real_base, real_target]) == real_base`.
  4. Raises `SecurityPathTraversalError` if validation fails.
- **`sanitize_child_name(child_name)`**:
  1. Strips path separators (`/`, `\`), relative components (`.`, `..`), null bytes, control characters.
  2. Normalizes spaces and restricts characters to standard alphanumeric, hyphens, and underscores.
  3. Provides safe default fallback (`"general"`).
- **`resolve_child_output_path(tenant_base_dir, child_name, subpath)`**:
  1. Safely joins tenant media root with sanitized child name and subpath.
  2. Guarantees containment within `tenant_base_dir`.

---

## 3. Proposed Module Architecture for `backend/security_isolation.py`

Below is the complete implementation design for `backend/security_isolation.py`.

```python
# SPDX-License-Identifier: MIT
# Security Isolation & Tenant Boundary Engine for Bright Horizons Photo Extractor
import fnmatch
import os
import re
import shutil
import subprocess
import uuid
from typing import Dict, Any, List, Optional, Callable, Tuple

# --- Custom Exceptions ---
class SecurityPathTraversalError(PermissionError):
    """Raised when a path traversal or tenant boundary violation is detected."""
    pass


class UserDataLockError(RuntimeError):
    """Raised when Chromium singleton lock operations fail."""
    pass


# ============================================================================
# 1. PLAYWRIGHT SINGLETON LOCK AVOIDANCE & USER_DATA MANAGEMENT
# ============================================================================

LOCK_FILE_PATTERNS = [
    "Singleton*",
    "RunningChromeVersion",
    "*Lock*",
    "*.lock",
    "LOCK",
    "DEVTOOLS_LOCK"
]

def clean_user_data_locks(user_data_dir: str) -> List[str]:
    """
    Safely removes residual Chromium singleton lock files and domain sockets.
    Returns list of removed lock file paths.
    """
    removed = []
    if not os.path.exists(user_data_dir):
        return removed

    for root, dirs, files in os.walk(user_data_dir):
        # Check files
        for fname in files:
            if any(fnmatch.fnmatch(fname, pat) for pat in LOCK_FILE_PATTERNS):
                fpath = os.path.join(root, fname)
                try:
                    if os.path.islink(fpath) or os.path.exists(fpath):
                        os.unlink(fpath) if os.path.islink(fpath) else os.remove(fpath)
                        removed.append(fpath)
                except Exception:
                    pass
        # Check dirs (some lock sockets are directory sockets)
        for dname in dirs:
            if any(fnmatch.fnmatch(dname, pat) for pat in LOCK_FILE_PATTERNS):
                dpath = os.path.join(root, dname)
                try:
                    shutil.rmtree(dpath, ignore_errors=True)
                    removed.append(dpath)
                except Exception:
                    pass
    return removed


def copy_user_data_dir(source_dir: str, target_dir: str) -> str:
    """
    Copies a Chromium user_data profile directory to a target directory,
    excluding all Singleton lock files, RunningChromeVersion, and *Lock* patterns.
    Uses system rsync if available, with pure-Python shutil fallback.
    """
    os.makedirs(target_dir, exist_ok=True)
    if not os.path.exists(source_dir):
        return target_dir

    # 1. Try fast-path via system rsync
    rsync_bin = shutil.which("rsync")
    if rsync_bin:
        cmd = [
            rsync_bin,
            "-a",
            "--delete",
            "--exclude=Singleton*",
            "--exclude=RunningChromeVersion",
            "--exclude=*Lock*",
            "--exclude=*.lock",
            "--exclude=LOCK",
            "--exclude=DEVTOOLS_LOCK",
            f"{source_dir.rstrip('/')}/",
            f"{target_dir.rstrip('/')}/"
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if res.returncode == 0:
                clean_user_data_locks(target_dir)
                return target_dir
        except Exception:
            pass  # Fallback to pure Python

    # 2. Pure-Python fallback using shutil.copytree
    ignore_func = shutil.ignore_patterns(*LOCK_FILE_PATTERNS)
    
    # Custom tree copy handling pre-existing target
    for root, dirs, files in os.walk(source_dir):
        rel_root = os.path.relpath(root, source_dir)
        target_root = os.path.normpath(os.path.join(target_dir, rel_root))
        
        ignored_names = ignore_func(root, dirs + files)
        
        os.makedirs(target_root, exist_ok=True)
        for f in files:
            if f in ignored_names:
                continue
            src_file = os.path.join(root, f)
            dst_file = os.path.join(target_root, f)
            try:
                shutil.copy2(src_file, dst_file)
            except Exception:
                pass

    clean_user_data_locks(target_dir)
    return target_dir


class IsolatedUserDataContext:
    """
    Context manager that creates an ephemeral copy of a tenant's user_data directory
    with all lock files excluded. Optionally syncs storage_state back on exit.
    """
    def __init__(self, source_user_data_dir: str, sync_back_state: bool = True):
        self.source_dir = source_user_data_dir
        self.sync_back = sync_back_state
        self.temp_dir = os.path.join(
            os.path.dirname(source_user_data_dir),
            f"user_data_isolated_{uuid.uuid4().hex[:8]}"
        )

    def __enter__(self) -> str:
        copy_user_data_dir(self.source_dir, self.temp_dir)
        return self.temp_dir

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.sync_back and os.path.exists(self.temp_dir):
            # Sync storage_state.json back if present
            temp_state = os.path.join(self.temp_dir, "storage_state.json")
            if os.path.exists(temp_state):
                os.makedirs(self.source_dir, exist_ok=True)
                target_state = os.path.join(self.source_dir, "storage_state.json")
                try:
                    shutil.copy2(temp_state, target_state)
                except Exception:
                    pass
        # Clean up ephemeral isolated directory
        if os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            except Exception:
                pass


# ============================================================================
# 2. CREDENTIAL & SENSITIVE DATA MASKING ENGINE
# ============================================================================

SENSITIVE_PATTERNS = [
    # Passwords in JSON / Key-Value / Log text
    (r'(?i)("?password"?\s*[:=]\s*["\'])([^"\']+)(["\'])', r'\g<1>***REDACTED_PASSWORD***\3'),
    (r'(?i)(password=)([^\s&]+)', r'\1***REDACTED_PASSWORD***'),
    
    # 6-digit MFA codes
    (r'(?i)(mfa_code|verification_code|code\s*[:=]\s*["\']?)(\d{6})(["\']?)', r'\1***REDACTED_MFA_CODE***\3'),
    (r'\b(code\s+)(\d{6})\b', r'\1***REDACTED_MFA_CODE***'),
    
    # Auth Tokens / JWTs
    (r'eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+', r'***REDACTED_JWT_TOKEN***'),
    (r'(?i)(bearer\s+)([A-Za-z0-9\-_\.=]+)', r'\1***REDACTED_BEARER_TOKEN***'),
    (r'(?i)(access_token|refresh_token|auth_token)\s*[:=]\s*["\']?([^\s"\']+)["\']?', r'\1=***REDACTED_TOKEN***'),
    
    # Sensitive Cookie values
    (r'(?i)(AWSALB|JSESSIONID|auth0_session)=([^;\s]+)', r'\1=***REDACTED_COOKIE***'),
]

def mask_sensitive_data(text: str) -> str:
    """
    Redacts passwords, MFA codes, tokens, and credentials from log messages or strings.
    """
    if not isinstance(text, str) or not text:
        return text
        
    sanitized = text
    for pattern, replacement in SENSITIVE_PATTERNS:
        sanitized = re.sub(pattern, replacement, sanitized)
    return sanitized


class SanitizedLogger:
    """
    Logger wrapper that guarantees all logged messages pass through mask_sensitive_data.
    """
    def __init__(self, target_callback: Optional[Callable[[str], None]] = None):
        self.target_callback = target_callback or (lambda msg: print(msg))

    def log(self, message: str) -> str:
        clean_msg = mask_sensitive_data(str(message))
        self.target_callback(clean_msg)
        return clean_msg

    def __call__(self, message: str) -> str:
        return self.log(message)


def sanitize_manifest_metadata(manifest_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Returns a copy of manifest/metadata dict with sensitive auth credentials or tokens removed.
    """
    if not isinstance(manifest_data, dict):
        return manifest_data

    clean_dict = {}
    forbidden_keys = {"password", "token", "secret", "cookies", "storage_state", "auth_header"}

    for k, v in manifest_data.items():
        if k.lower() in forbidden_keys:
            continue
        if isinstance(v, dict):
            clean_dict[k] = sanitize_manifest_metadata(v)
        elif isinstance(v, list):
            clean_dict[k] = [sanitize_manifest_metadata(item) if isinstance(item, dict) else mask_sensitive_data(str(item)) for item in v]
        elif isinstance(v, str):
            clean_dict[k] = mask_sensitive_data(v)
        else:
            clean_dict[k] = v

    return clean_dict


# ============================================================================
# 3. PATH TRAVERSAL & TENANT ISOLATION BOUNDARY ENGINE
# ============================================================================

def canonicalize_and_validate_path(base_dir: str, target_path: str) -> str:
    """
    Resolves canonical real paths and verifies that target_path is strictly inside base_dir.
    Prevents path traversal, symlink escapes, null-byte injection, and prefix collisions.
    Raises SecurityPathTraversalError if target_path escapes base_dir.
    """
    if "\x00" in target_path or "\x00" in base_dir:
        raise SecurityPathTraversalError("Null byte injection detected in path string.")

    real_base = os.path.realpath(base_dir)
    real_target = os.path.realpath(os.path.join(base_dir, target_path))

    # Add trailing directory separator to base path to prevent prefix collision
    # (e.g. /data/tenants/tenant1 vs /data/tenants/tenant10)
    real_base_sep = real_base if real_base.endswith(os.sep) else real_base + os.sep

    # Verify containment via commonpath and prefix check
    try:
        common = os.path.commonpath([real_base, real_target])
    except ValueError:
        # Happens on Windows if paths are on different drives
        raise SecurityPathTraversalError(f"Cross-drive path traversal detected: {target_path}")

    if common != real_base or not (real_target == real_base or real_target.startswith(real_base_sep)):
        raise SecurityPathTraversalError(
            f"Security Violation: Path '{target_path}' escapes base directory '{base_dir}'"
        )

    return real_target


def sanitize_child_name(child_name: str) -> str:
    """
    Sanitizes child folder names (e.g. 'Byron', 'Catherine') for use in output directories.
    Strips path separators, relative path characters ('..'), null bytes, and non-alphanumeric symbols.
    Returns safe child directory name. Defaults to 'general'.
    """
    if not child_name or not isinstance(child_name, str):
        return "general"

    # Remove null bytes and path separators
    name = child_name.replace("\x00", "").replace("/", "").replace("\\", "").strip()
    
    # Strip relative path navigation tokens
    name = re.sub(r'^\.+', '', name)
    
    # Allow alphanumeric, spaces, hyphens, and underscores
    name = re.sub(r'[^\w\s-]', '', name).strip()
    
    # Normalize internal spaces to single space or underscore
    name = re.sub(r'\s+', '_', name)

    if not name or name.lower() in {"all", "all_kids", "none"}:
        return "general"

    return name[:64].capitalize()


def resolve_child_output_path(tenant_base_dir: str, child_name: str, subpath: str) -> str:
    """
    Constructs a safe, validated output directory path for a specific child under a tenant directory.
    Format: <tenant_base_dir>/media/<sanitized_child>/<subpath>
    Enforces strict path containment.
    """
    clean_child = sanitize_child_name(child_name)
    relative_path = os.path.join("media", clean_child, subpath.lstrip("/\\"))
    return canonicalize_and_validate_path(tenant_base_dir, relative_path)
```

---

## 4. Integration Blueprint for Existing Backend Codebase

### A. Refactoring `backend/database.py`
In `TenantStorage`:
1. Import `canonicalize_and_validate_path`, `sanitize_child_name`, and `resolve_child_output_path` from `backend.security_isolation`.
2. Update `add_media_entry` and `get_media_file_path`:
   ```python
   # Replace old string startswith check with:
   abs_path = canonicalize_and_validate_path(self.tenant_dir, item["storage_path"])
   ```
3. Update tenant purge and session clear functions to use `clean_user_data_locks`.

### B. Refactoring `backend/scraper_engine.py`
In `ScraperJob`:
1. Import `IsolatedUserDataContext`, `clean_user_data_locks`, `SanitizedLogger`, `mask_sensitive_data`, and `sanitize_child_name`.
2. Wrap `self.log_callback` with `SanitizedLogger`:
   ```python
   self.log_callback = SanitizedLogger(log_callback or (lambda msg: print(f"[{self.email}] {msg}"))).log
   ```
3. Update persistent context launch to use `IsolatedUserDataContext(user_data_dir)` when running diagnostic or parallel runs, or use `clean_user_data_locks(user_data_dir)` prior to Playwright launch.

### C. Refactoring `backend/server.py`
1. Use `SanitizedLogger` for all FastAPI logs and active verification progress state updates.
2. Apply `sanitize_manifest_metadata` when returning `/api/manifest` responses to ensure no internal tokens or secrets are exposed.

---

## 5. Testing & Verification Plan

`backend/tests/test_security_isolation.py` will verify all security guarantees:

1. **Lock Avoidance Tests**:
   - Create mock `user_data` directory with `SingletonLock` symlink, `RunningChromeVersion`, `*Lock*` files, and session cookies.
   - Run `copy_user_data_dir` and assert all lock files are removed while session cookies are preserved.
   - Verify `IsolatedUserDataContext` creates ephemeral copy and cleans up after context exit.

2. **Data Redaction Tests**:
   - Test `mask_sensitive_data` against password strings, 6-digit MFA codes, JWT tokens, and Auth0 headers.
   - Verify `SanitizedLogger` intercepts and redacts log callbacks.
   - Verify `sanitize_manifest_metadata` strips forbidden credential keys from dictionary payloads.

3. **Path Traversal & Isolation Tests**:
   - Test `canonicalize_and_validate_path` with `../`, null bytes, symlinks, and cross-tenant prefix overlaps (e.g. `/data/tenants/tenant1` vs `/data/tenants/tenant10`). Assert `SecurityPathTraversalError` is raised.
   - Test `sanitize_child_name` with invalid/malicious child names (`../../Byron`, `Catherine/..`, `\x00Child`). Assert names are properly sanitized.

---

## 6. Summary of Architectural Recommendations

1. **Adopt `backend/security_isolation.py` as a dedicated isolation module** complementing `backend/security.py`.
2. **Replace all string `startswith` prefix checks** across the codebase with `canonicalize_and_validate_path()`.
3. **Enforce `SanitizedLogger`** across `ScraperJob` and `server.py` to prevent log leakage of passwords, tokens, and MFA codes.
4. **Use `copy_user_data_dir` and `IsolatedUserDataContext`** for all Playwright profile launches to eliminate Chromium `TargetClosedError` singleton lock crashes.
