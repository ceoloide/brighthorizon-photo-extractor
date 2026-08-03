# SPDX-License-Identifier: MIT
"""
Empirical Security Stress Test Harness for backend/security_isolation.py
"""

import os
import sys
import shutil
import tempfile
import traceback

from backend.security_isolation import (
    clean_user_data_locks,
    prepare_isolated_user_data,
    IsolatedUserDataContext,
    mask_sensitive_data,
    SanitizedLogger,
    canonicalize_and_validate_path,
    sanitize_child_name,
    resolve_child_output_path,
    SecurityPathTraversalError,
    LOCK_FILE_PATTERNS
)

def run_stress_tests():
    print("=== STARTING EMPIRICAL SECURITY STRESS TESTS ===")
    results = []

    def log_test(name: str, passed: bool, details: str = ""):
        status = "PASS" if passed else "FAIL"
        print(f"[{status}] {name} - {details}")
        results.append({"name": name, "passed": passed, "details": details})

    # Test Category 1: Tenant Prefix Collision Stress Tests
    try:
        with tempfile.TemporaryDirectory() as parent:
            tenant1 = os.path.join(parent, "tenant1")
            tenant10 = os.path.join(parent, "tenant10")
            tenant1_extra = os.path.join(parent, "tenant1_extra")
            os.makedirs(tenant1, exist_ok=True)
            os.makedirs(tenant10, exist_ok=True)
            os.makedirs(tenant1_extra, exist_ok=True)

            # Case 1.1: Direct relative escape to tenant10 from tenant1
            blocked_1 = False
            try:
                canonicalize_and_validate_path(tenant1, "../tenant10/data.txt")
            except SecurityPathTraversalError:
                blocked_1 = True
            log_test("Prefix Collision: tenant1 to tenant10 relative path", blocked_1)

            # Case 1.2: Relative escape to tenant1_extra
            blocked_2 = False
            try:
                canonicalize_and_validate_path(tenant1, "../tenant1_extra/data.txt")
            except SecurityPathTraversalError:
                blocked_2 = True
            log_test("Prefix Collision: tenant1 to tenant1_extra relative path", blocked_2)

            # Case 1.3: Target path equals base_dir prefix
            blocked_3 = False
            try:
                canonicalize_and_validate_path(tenant1, "../tenant10")
            except SecurityPathTraversalError:
                blocked_3 = True
            log_test("Prefix Collision: tenant1 to tenant10 directory target", blocked_3)

            # Case 1.4: Base dir with trailing slash vs without
            valid_slash = canonicalize_and_validate_path(tenant1 + "/", "file.txt")
            valid_noslash = canonicalize_and_validate_path(tenant1, "file.txt")
            log_test("Prefix Collision: Trailing slash consistency", valid_slash == valid_noslash)

    except Exception as e:
        log_test("Tenant Prefix Collision Category", False, str(e))

    # Test Category 2: Null Byte Injection Stress Tests
    try:
        with tempfile.TemporaryDirectory() as base:
            # Case 2.1: Null byte in target_path extension
            blocked_null_ext = False
            try:
                canonicalize_and_validate_path(base, "photo.jpg\x00.php")
            except SecurityPathTraversalError:
                blocked_null_ext = True
            log_test("Null Byte: Injection in extension", blocked_null_ext)

            # Case 2.2: Null byte in target_path traversal
            blocked_null_trav = False
            try:
                canonicalize_and_validate_path(base, "\x00/../../etc/passwd")
            except SecurityPathTraversalError:
                blocked_null_trav = True
            log_test("Null Byte: Injection in traversal path", blocked_null_trav)

            # Case 2.3: Null byte in base_dir
            blocked_null_base = False
            try:
                canonicalize_and_validate_path(base + "\x00", "photo.jpg")
            except SecurityPathTraversalError:
                blocked_null_base = True
            log_test("Null Byte: Injection in base_dir", blocked_null_base)

            # Case 2.4: Null byte in child name sanitization
            sanitized = sanitize_child_name("Child\x00Name")
            log_test("Null Byte: sanitize_child_name removes null byte", "\x00" not in sanitized and sanitized == "Childname")

    except Exception as e:
        log_test("Null Byte Injection Category", False, str(e))

    # Test Category 3: Relative Path Traversal Stress Tests
    try:
        with tempfile.TemporaryDirectory() as base:
            # Case 3.1: Deep relative traversal
            blocked_deep = False
            try:
                canonicalize_and_validate_path(base, "a/b/c/../../../../../../etc/passwd")
            except SecurityPathTraversalError:
                blocked_deep = True
            log_test("Path Traversal: Deep ../ escape", blocked_deep)

            # Case 3.2: Traversal with absolute target_path
            blocked_abs = False
            try:
                canonicalize_and_validate_path(base, "/etc/passwd")
            except SecurityPathTraversalError:
                blocked_abs = True
            log_test("Path Traversal: Absolute target path /etc/passwd", blocked_abs)

            # Case 3.3: Backslash path traversal (Windows style on Linux)
            blocked_win = False
            try:
                canonicalize_and_validate_path(base, "..\\..\\etc\\passwd")
            except SecurityPathTraversalError:
                blocked_win = True
            log_test("Path Traversal: Backslash navigation", blocked_win)

            # Case 3.4: Child output path traversal attempt via child_name
            res_path = resolve_child_output_path(base, "../../../admin", "file.png")
            real_base = os.path.realpath(base)
            contained = res_path.startswith(real_base)
            log_test("Path Traversal: resolve_child_output_path containment", contained)

    except Exception as e:
        log_test("Relative Path Traversal Category", False, str(e))

    # Test Category 4: Symlink Target Escapes Stress Tests
    try:
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as secret_dir:
            secret_file = os.path.join(secret_dir, "secret.txt")
            with open(secret_file, "w") as f:
                f.write("CONFIDENTIAL")

            # Case 4.1: File symlink inside base pointing to external file
            symlink_file = os.path.join(base, "symlink_file.txt")
            os.symlink(secret_file, symlink_file)

            blocked_symfile = False
            try:
                canonicalize_and_validate_path(base, "symlink_file.txt")
            except SecurityPathTraversalError:
                blocked_symfile = True
            log_test("Symlink Escape: Direct file symlink escape", blocked_symfile)

            # Case 4.2: Directory symlink inside base pointing to external directory
            symlink_dir = os.path.join(base, "external_dir")
            os.symlink(secret_dir, symlink_dir)

            blocked_symdir = False
            try:
                canonicalize_and_validate_path(base, "external_dir/secret.txt")
            except SecurityPathTraversalError:
                blocked_symdir = True
            log_test("Symlink Escape: Directory symlink escape", blocked_symdir)

            # Case 4.3: Relative symlink escaping base directory
            rel_symlink = os.path.join(base, "rel_symlink")
            os.symlink("../../", rel_symlink)

            blocked_relsym = False
            try:
                canonicalize_and_validate_path(base, "rel_symlink/etc/passwd")
            except SecurityPathTraversalError:
                blocked_relsym = True
            log_test("Symlink Escape: Relative symlink escape", blocked_relsym)

            # Case 4.4: Base dir itself is a symlink to another directory
            link_base = os.path.join(secret_dir, "sym_base")
            os.symlink(base, link_base)

            target_in_symbase = canonicalize_and_validate_path(link_base, "normal_file.txt")
            log_test("Symlink Escape: Base directory is symlink", target_in_symbase.startswith(os.path.realpath(base)))

    except Exception as e:
        log_test("Symlink Target Escapes Category", False, str(e))

    # Test Category 5: Lock Cleanup with Missing / Dangling Files & Race Conditions
    try:
        with tempfile.TemporaryDirectory() as user_data:
            # Case 5.1: Missing user_data directory
            non_existent = os.path.join(user_data, "does_not_exist")
            removed_empty = clean_user_data_locks(non_existent)
            log_test("Lock Cleanup: Non-existent directory handling", removed_empty == [])

            # Case 5.2: Dangling symlink matching lock pattern
            dangling_link = os.path.join(user_data, "SingletonLock")
            os.symlink("/tmp/non_existent_target_12345", dangling_link)
            
            removed_dangling = clean_user_data_locks(user_data)
            link_removed = not os.path.lexists(dangling_link)
            log_test("Lock Cleanup: Dangling symlink lock removal", link_removed and len(removed_dangling) == 1)

            # Case 5.3: Lock pattern symlink pointing to sensitive system file (/etc/passwd)
            passwd_symlink = os.path.join(user_data, "SingletonCookie")
            target_passwd = "/etc/passwd"
            if os.path.exists(target_passwd):
                os.symlink(target_passwd, passwd_symlink)
                removed_sym = clean_user_data_locks(user_data)
                sym_unlinked = not os.path.lexists(passwd_symlink)
                target_intact = os.path.exists(target_passwd)
                log_test("Lock Cleanup: Symlink lock targeting /etc/passwd unlinked without touching target", sym_unlinked and target_intact)
            else:
                log_test("Lock Cleanup: /etc/passwd test skipped", True, "/etc/passwd does not exist")

            # Case 5.4: Directory lock cleanup
            lock_dir = os.path.join(user_data, "DEVTOOLS_LOCK")
            os.makedirs(lock_dir, exist_ok=True)
            with open(os.path.join(lock_dir, "internal.lock"), "w") as f:
                f.write("lock")
            
            removed_dir = clean_user_data_locks(user_data)
            dir_removed = not os.path.exists(lock_dir)
            log_test("Lock Cleanup: Lock directory rmtree", dir_removed)

    except Exception as e:
        log_test("Lock Cleanup Category", False, str(e))

    # Test Category 6: Data Redaction & Logger Stress Tests
    try:
        # Complex multi-line log with mixed sensitive data
        complex_log = """
        User login attempt: username='admin', password='My$uperP@ssw0rd!123'
        Session cookie: JSESSIONID=abc123xyz890; AWSALB=test_alb_token
        API header: Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisSignature
        MFA prompt response: verification_code='849201' entered at 2026-07-31
        Custom secret: SECRET_API_KEY_VAL_9999
        """
        masked = mask_sensitive_data(complex_log, custom_secrets=["SECRET_API_KEY_VAL_9999"])

        leaks = []
        if "My$uperP@ssw0rd!123" in masked: leaks.append("password")
        if "abc123xyz890" in masked: leaks.append("JSESSIONID")
        if "doNotLeakThisSignature" in masked: leaks.append("JWT")
        if "849201" in masked: leaks.append("MFA code")
        if "SECRET_API_KEY_VAL_9999" in masked: leaks.append("custom secret")

        log_test("Data Redaction: Complex multi-pattern log masking", len(leaks) == 0, f"Leaks found: {leaks}" if leaks else "All masked")

    except Exception as e:
        log_test("Data Redaction Category", False, str(e))

    print("\n=== SUMMARY ===")
    total = len(results)
    passed_count = sum(1 for r in results if r["passed"])
    failed_count = total - passed_count
    print(f"Total Tests: {total} | Passed: {passed_count} | Failed: {failed_count}")

    return failed_count == 0

if __name__ == "__main__":
    success = run_stress_tests()
    sys.exit(0 if success else 1)
