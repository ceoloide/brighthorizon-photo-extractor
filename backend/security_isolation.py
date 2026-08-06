# SPDX-License-Identifier: MIT
"""
Security Isolation & Tenant Boundary Module for Bright Horizons Photo Extractor.

Provides Chromium persistent profile lock avoidance, ephemeral isolated context management,
strict canonical path traversal validation, credential & MFA log masking, and child directory sanitization.
Spec reference: .agents/explorer_m1_2/analysis.md & .agents/explorer_m1_3/analysis.md
"""

import fnmatch
import os
import re
import shutil
import subprocess
import uuid
from typing import Dict, Any, List, Optional, Callable, Tuple

# Custom Exceptions
class SecurityPathTraversalError(PermissionError):
    """Raised when a path traversal or tenant boundary violation is detected."""
    pass


class UserDataLockError(RuntimeError):
    """Raised when Chromium singleton lock operations fail."""
    pass


# Lock file patterns to ignore/purge
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

    Args:
        user_data_dir: Path to the user_data directory.

    Returns:
        List of removed lock file paths.
    """
    removed: List[str] = []
    if not os.path.exists(user_data_dir):
        return removed

    if not os.access(user_data_dir, os.W_OK):
        try:
            os.chmod(user_data_dir, 0o777)
        except Exception:
            pass

    for root, dirs, files in os.walk(user_data_dir):
        if not os.access(root, os.W_OK):
            try:
                os.chmod(root, 0o777)
            except Exception:
                pass
        # Check files and symlinks
        for fname in files:
            if any(fnmatch.fnmatch(fname, pat) for pat in LOCK_FILE_PATTERNS):
                fpath = os.path.join(root, fname)
                try:
                    if os.path.islink(fpath) or os.path.exists(fpath):
                        os.unlink(fpath) if os.path.islink(fpath) else os.remove(fpath)
                        removed.append(fpath)
                except Exception:
                    pass

        # Check directories (some lock sockets are directory sockets)
        for dname in dirs:
            if any(fnmatch.fnmatch(dname, pat) for pat in LOCK_FILE_PATTERNS):
                dpath = os.path.join(root, dname)
                try:
                    shutil.rmtree(dpath, ignore_errors=True)
                    removed.append(dpath)
                except Exception:
                    pass

    return removed


def prepare_isolated_user_data(source_dir: str, target_dir: str) -> str:
    """
    Safely clones persistent Playwright user data directory (Rule 1).
    Excludes Singleton locks during copy using system rsync fast-path with pure-Python shutil fallback.

    Args:
        source_dir: Source user_data path.
        target_dir: Target isolated directory path.

    Returns:
        Absolute path to target_dir.
    """
    abs_source = os.path.abspath(source_dir)
    abs_target = os.path.abspath(target_dir)

    os.makedirs(abs_target, exist_ok=True)
    if not os.path.exists(abs_source):
        clean_user_data_locks(abs_target)
        return abs_target

    # 1. System rsync fast-path
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
            f"{abs_source.rstrip('/')}/",
            f"{abs_target.rstrip('/')}/"
        ]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if res.returncode == 0:
                clean_user_data_locks(abs_target)
                return abs_target
        except Exception:
            pass

    # 2. Pure-Python fallback using shutil.copytree logic
    ignore_func = shutil.ignore_patterns(*LOCK_FILE_PATTERNS)
    for root, dirs, files in os.walk(abs_source):
        rel_root = os.path.relpath(root, abs_source)
        target_root = os.path.normpath(os.path.join(abs_target, rel_root))

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

    clean_user_data_locks(abs_target)
    return abs_target


class IsolatedUserDataContext:
    """
    Context manager that creates an ephemeral copy of a tenant's user_data directory
    with all lock files excluded. Optionally syncs storage_state.json back on exit.
    """
    def __init__(self, source_user_data_dir: str, sync_back_state: bool = True):
        self.source_dir = os.path.abspath(source_user_data_dir)
        self.sync_back = sync_back_state
        base_parent = os.path.dirname(self.source_dir) or "."
        self.temp_dir = os.path.join(
            base_parent,
            f"user_data_isolated_{uuid.uuid4().hex[:8]}"
        )

    def __enter__(self) -> str:
        prepare_isolated_user_data(self.source_dir, self.temp_dir)
        return self.temp_dir

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.sync_back and os.path.exists(self.temp_dir):
            temp_state = os.path.join(self.temp_dir, "storage_state.json")
            if os.path.exists(temp_state):
                os.makedirs(self.source_dir, exist_ok=True)
                target_state = os.path.join(self.source_dir, "storage_state.json")
                try:
                    shutil.copy2(temp_state, target_state)
                except Exception:
                    pass

        if os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir, ignore_errors=True)
            except Exception:
                pass


# Sensitive data masking patterns
SENSITIVE_PATTERNS = [
    # Passwords in JSON / Key-Value / Log text
    (r'(?i)("?password"?\s*[:=]\s*["\'])([^"\']+)(["\'])', r'\g<1>***REDACTED_PASSWORD***\3'),
    (r'(?i)(password=)([^\s&]+)', r'\1***REDACTED_PASSWORD***'),

    # 6-digit MFA codes
    (r'(?i)(mfa_code|verification_code|code\s*[:=]\s*["\']?)(\d{6})(["\']?)', r'\1***REDACTED_MFA_CODE***\3'),
    (r'\b(code\s+)(\d{6})\b', r'\1***REDACTED_MFA_CODE***'),
    (r'\b(code|mfa|verification)\s*[:=]\s*(\d{6})\b', r'\1: ***REDACTED_MFA_CODE***'),

    # Auth Tokens / JWTs
    (r'eyJ[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+\.[A-Za-z0-9-_=]+', r'***REDACTED_JWT_TOKEN***'),
    (r'(?i)(bearer\s+)([A-Za-z0-9\-_\.=]+)', r'\1***REDACTED_BEARER_TOKEN***'),
    (r'(?i)(access_token|refresh_token|auth_token)\s*[:=]\s*["\']?([^\s"\']+)["\']?', r'\1=***REDACTED_TOKEN***'),

    # Sensitive Cookie values
    (r'(?i)(AWSALB|JSESSIONID|auth0_session)=([^;\s]+)', r'\1=***REDACTED_COOKIE***'),
]


def mask_sensitive_data(text: str, custom_secrets: Optional[List[str]] = None) -> str:
    """
    Redacts passwords, MFA codes, tokens, credentials, and custom secrets from strings.
    """
    if not isinstance(text, str) or not text:
        return text

    sanitized = text
    if custom_secrets:
        for secret in custom_secrets:
            if secret and len(secret) > 2:
                sanitized = sanitized.replace(secret, "[MASKED_SECRET]")

    for pattern, replacement in SENSITIVE_PATTERNS:
        sanitized = re.sub(pattern, replacement, sanitized)

    return sanitized


class SanitizedLogger:
    """
    Logger wrapper that guarantees all logged messages pass through mask_sensitive_data.
    """
    def __init__(self, target_callback: Optional[Callable[[str], None]] = None):
        self.target_callback = target_callback or (lambda msg: None)

    def log(self, message: str) -> str:
        clean_msg = mask_sensitive_data(str(message))
        self.target_callback(clean_msg)
        return clean_msg

    def __call__(self, message: str) -> str:
        return self.log(message)


def canonicalize_and_validate_path(base_dir: str, target_path: str) -> str:
    """
    Resolves realpaths and verifies that target_path is strictly inside base_dir.
    Prevents path traversal, symlink escapes, null-byte injection, and prefix collisions.

    Raises SecurityPathTraversalError if target_path escapes base_dir.
    """
    if not isinstance(target_path, str) or not isinstance(base_dir, str):
        raise SecurityPathTraversalError("Path arguments must be strings.")

    if "\x00" in target_path or "\x00" in base_dir:
        raise SecurityPathTraversalError("Null byte injection detected in path string.")

    real_base = os.path.realpath(base_dir)
    real_target = os.path.realpath(os.path.join(base_dir, target_path))

    # Real base separator prevents prefix overlap (e.g. /data/tenant1 vs /data/tenant10)
    real_base_sep = real_base if real_base.endswith(os.sep) else real_base + os.sep

    try:
        common = os.path.commonpath([real_base, real_target])
    except ValueError:
        raise SecurityPathTraversalError(f"Cross-drive path traversal detected: {target_path}")

    if common != real_base or not (real_target == real_base or real_target.startswith(real_base_sep)):
        raise SecurityPathTraversalError(
            f"Security Violation: Path '{target_path}' escapes base directory '{base_dir}'"
        )

    return real_target


def sanitize_child_name(child_name: str) -> str:
    """
    Sanitizes child folder names (e.g. 'Byron', 'Catherine') for use in output directories.
    Strips path separators, relative navigation tokens ('..'), null bytes, and non-alphanumeric symbols.
    Defaults to 'general'.
    """
    if not child_name or not isinstance(child_name, str):
        return "general"

    # Remove null bytes and path separators
    name = child_name.replace("\x00", "").replace("/", "").replace("\\", "").strip()

    # Strip relative path navigation tokens
    name = re.sub(r'^\.+', '', name)

    # Allow alphanumeric, spaces, hyphens, and underscores
    name = re.sub(r'[^\w\s-]', '', name).strip()

    # Normalize internal spaces to single underscore
    name = re.sub(r'\s+', '_', name)

    if not name or name.lower() in {"all", "all_kids", "none"}:
        return "general"

    return name[:64].capitalize()


def resolve_child_output_path(base_dir: str, child_name: str, relative_filename: str) -> str:
    """
    Constructs a safe, validated output directory path for a specific child under a base directory.
    Format: <base_dir>/media/<sanitized_child>/<relative_filename>
    Enforces strict path containment.
    """
    clean_child = sanitize_child_name(child_name)
    relative_path = os.path.join("media", clean_child, relative_filename.lstrip("/\\"))
    return canonicalize_and_validate_path(base_dir, relative_path)
