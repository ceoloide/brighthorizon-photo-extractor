# SPDX-License-Identifier: MIT
"""
Unit tests for backend/security_isolation.py.
"""

import os
import shutil
import tempfile
import pytest
from backend.security_isolation import (
    clean_user_data_locks,
    prepare_isolated_user_data,
    IsolatedUserDataContext,
    mask_sensitive_data,
    SanitizedLogger,
    canonicalize_and_validate_path,
    sanitize_child_name,
    resolve_child_output_path,
    SecurityPathTraversalError
)


def test_clean_user_data_locks():
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create lock files and normal files
        singleton_lock = os.path.join(temp_dir, "SingletonLock")
        chrome_ver = os.path.join(temp_dir, "RunningChromeVersion")
        custom_lock = os.path.join(temp_dir, "app.lock")
        pref_file = os.path.join(temp_dir, "Preferences")

        with open(singleton_lock, "w") as f:
            f.write("lock")
        with open(chrome_ver, "w") as f:
            f.write("120.0")
        with open(custom_lock, "w") as f:
            f.write("lock")
        with open(pref_file, "w") as f:
            f.write("{}")

        nested_dir = os.path.join(temp_dir, "Default")
        os.makedirs(nested_dir, exist_ok=True)
        nested_lock = os.path.join(nested_dir, "LOCK")
        with open(nested_lock, "w") as f:
            f.write("lock")

        removed = clean_user_data_locks(temp_dir)
        assert len(removed) == 4
        assert not os.path.exists(singleton_lock)
        assert not os.path.exists(chrome_ver)
        assert not os.path.exists(custom_lock)
        assert not os.path.exists(nested_lock)
        assert os.path.exists(pref_file)


def test_prepare_isolated_user_data():
    with tempfile.TemporaryDirectory() as src_dir, tempfile.TemporaryDirectory() as target_dir:
        # Create source files
        lock_file = os.path.join(src_dir, "SingletonCookie")
        data_file = os.path.join(src_dir, "Cookies")

        with open(lock_file, "w") as f:
            f.write("lock")
        with open(data_file, "w") as f:
            f.write("session_data")

        res_path = prepare_isolated_user_data(src_dir, target_dir)
        assert res_path == target_dir
        assert os.path.exists(os.path.join(target_dir, "Cookies"))
        assert not os.path.exists(os.path.join(target_dir, "SingletonCookie"))


def test_isolated_user_data_context():
    with tempfile.TemporaryDirectory() as src_dir:
        state_file = os.path.join(src_dir, "storage_state.json")
        with open(state_file, "w") as f:
            f.write('{"cookies": []}')

        temp_path = None
        with IsolatedUserDataContext(src_dir, sync_back_state=True) as isolated_dir:
            temp_path = isolated_dir
            assert os.path.exists(isolated_dir)
            assert os.path.exists(os.path.join(isolated_dir, "storage_state.json"))
            # Mutate state in context
            with open(os.path.join(isolated_dir, "storage_state.json"), "w") as f:
                f.write('{"cookies": ["updated"]}')

        # After exiting context, temp directory is cleaned up
        assert not os.path.exists(temp_path)
        # Mutated state is synced back
        with open(state_file, "r") as f:
            content = f.read()
            assert "updated" in content


def test_mask_sensitive_data():
    # Passwords
    raw_pass = '{"username": "user", "password": "super_secret_pass"}'
    masked_pass = mask_sensitive_data(raw_pass)
    assert "super_secret_pass" not in masked_pass
    assert "***REDACTED_PASSWORD***" in masked_pass

    # MFA codes
    raw_mfa = "User entered verification code: 654321 for login"
    masked_mfa = mask_sensitive_data(raw_mfa)
    assert "654321" not in masked_mfa
    assert "***REDACTED_MFA_CODE***" in masked_mfa

    # JWT tokens
    raw_jwt = "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIiwibmFtZSI6IkpvaG4gRG9lIiwiaWF0IjoxNTE2MjM5MDIyfQ.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    masked_jwt = mask_sensitive_data(raw_jwt)
    assert "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c" not in masked_jwt
    assert "***REDACTED_JWT_TOKEN***" in masked_jwt

    # Custom secrets
    custom_secret = "MY_PRIVATE_KEY_123"
    raw_custom = f"Connecting with key {custom_secret}"
    masked_custom = mask_sensitive_data(raw_custom, custom_secrets=[custom_secret])
    assert custom_secret not in masked_custom
    assert "[MASKED_SECRET]" in masked_custom

    # Logger wrapper
    logs = []
    logger = SanitizedLogger(lambda msg: logs.append(msg))
    logger("Submitting MFA code=123456")
    assert len(logs) == 1
    assert "123456" not in logs[0]
    assert "***REDACTED_MFA_CODE***" in logs[0]


def test_canonicalize_and_validate_path_valid():
    with tempfile.TemporaryDirectory() as base_dir:
        target = canonicalize_and_validate_path(base_dir, "media/Byron/photo.jpg")
        assert target.startswith(os.path.realpath(base_dir))
        assert target.endswith("media/Byron/photo.jpg")


def test_canonicalize_and_validate_path_traversal():
    with tempfile.TemporaryDirectory() as base_dir:
        # Relative traversal
        with pytest.raises(SecurityPathTraversalError):
            canonicalize_and_validate_path(base_dir, "../outside.txt")

        # Deep traversal
        with pytest.raises(SecurityPathTraversalError):
            canonicalize_and_validate_path(base_dir, "media/../../../../etc/passwd")

        # Null byte injection
        with pytest.raises(SecurityPathTraversalError):
            canonicalize_and_validate_path(base_dir, "photo.jpg\x00.exe")

    # Prefix overlap attempt
    with tempfile.TemporaryDirectory() as parent_dir:
        tenant1_dir = os.path.join(parent_dir, "tenant1")
        tenant10_dir = os.path.join(parent_dir, "tenant10")
        os.makedirs(tenant1_dir, exist_ok=True)
        os.makedirs(tenant10_dir, exist_ok=True)

        with pytest.raises(SecurityPathTraversalError):
            canonicalize_and_validate_path(tenant1_dir, "../tenant10/data.file")


def test_sanitize_child_name():
    assert sanitize_child_name("Byron") == "Byron"
    assert sanitize_child_name("../../Byron") == "Byron"
    assert sanitize_child_name("Catherine/..") == "Catherine"
    assert sanitize_child_name("\x00Child") == "Child"
    assert sanitize_child_name("all") == "general"
    assert sanitize_child_name("") == "general"
    assert sanitize_child_name(None) == "general"
    assert sanitize_child_name("Mary Jane") == "Mary_jane"


def test_resolve_child_output_path():
    with tempfile.TemporaryDirectory() as base_dir:
        resolved = resolve_child_output_path(base_dir, "Byron", "2026/06/photo.png")
        real_base = os.path.realpath(base_dir)
        assert resolved.startswith(real_base)
        assert "media" in resolved
        assert "Byron" in resolved
        assert resolved.endswith("2026/06/photo.png")
