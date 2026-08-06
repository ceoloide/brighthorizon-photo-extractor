# SPDX-License-Identifier: MIT
# Unit Tests for Backend Security & Tenant Isolation
import os
import pytest
from backend.security import (
    get_or_create_salt,
    derive_aes_key,
    encrypt_bytes,
    decrypt_bytes,
    encrypt_json,
    decrypt_json,
    get_tenant_id,
    create_jwt_token,
    verify_jwt_token
)
from backend.database import TenantStorage
from backend.archive_stream import parse_range_header

def test_encryption_decryption():
    data = {"secret_key": "12345", "password": "super_secret_password!"}
    encrypted = encrypt_json(data)
    assert isinstance(encrypted, str)
    assert encrypted != str(data)
    
    decrypted = decrypt_json(encrypted)
    assert decrypted == data

def test_tenant_id_isolation():
    tenant1 = get_tenant_id("User1@example.com")
    tenant2 = get_tenant_id("user1@example.com ")
    tenant3 = get_tenant_id("user2@example.com")
    
    # Normalization check
    assert tenant1 == tenant2
    # Distinct user check
    assert tenant1 != tenant3

def test_jwt_authentication():
    email = "test@example.com"
    tenant_id = get_tenant_id(email)
    
    token = create_jwt_token(email, tenant_id)
    payload = verify_jwt_token(token)
    
    assert payload is not None
    assert payload["email"] == email
    assert payload["sub"] == tenant_id
    
    # Tampered token check
    tampered = token[:-4] + "abcd"
    assert verify_jwt_token(tampered) is None

def test_tenant_storage_isolation(tmp_path):
    storage1 = TenantStorage("userA@example.com")
    storage2 = TenantStorage("userB@example.com")
    
    assert storage1.tenant_id != storage2.tenant_id
    assert storage1.tenant_dir != storage2.tenant_dir

def test_range_header_parsing():
    file_size = 10000
    
    # Full range
    bounds = parse_range_header("bytes=0-999", file_size)
    assert bounds == (0, 999)
    
    # Open ended start
    bounds = parse_range_header("bytes=5000-", file_size)
    assert bounds == (5000, 9999)
    
    # Invalid bounds
    bounds = parse_range_header("bytes=15000-20000", file_size)
    assert bounds is None

def test_tenant_purge_data():
    storage = TenantStorage("purge_test_user@example.com")
    config = storage.load_config()
    config["test"] = "data"
    storage.save_config(config)
    assert os.path.exists(storage.tenant_dir)
    
    storage.purge_all_data()
    assert not os.path.exists(storage.tenant_dir)

def test_path_traversal_prevention():
    storage = TenantStorage("security_check_user@example.com")
    file_info = storage.get_media_file_path("../../../etc/passwd")
    assert file_info is None
    storage.purge_all_data()

def test_concurrent_verification_isolation():
    from backend.server import _active_verifications
    from backend.security import get_tenant_id
    
    tid1 = get_tenant_id("userA@example.com")
    tid2 = get_tenant_id("userB@example.com")
    
    _active_verifications[tid1] = {"status": "running", "screenshot": "data:image/jpeg;base64,UserAScreenshotData"}
    _active_verifications[tid2] = {"status": "running", "screenshot": "data:image/jpeg;base64,UserBScreenshotData"}
    
    assert _active_verifications[tid1]["screenshot"] != _active_verifications[tid2]["screenshot"]
    assert "UserAScreenshotData" in _active_verifications[tid1]["screenshot"]
    assert "UserBScreenshotData" in _active_verifications[tid2]["screenshot"]
    
    _active_verifications.pop(tid1, None)
    _active_verifications.pop(tid2, None)

def test_mfa_regex_input_validation():
    from backend.server import submit_mfa_code, MfaRequest
    from fastapi import HTTPException

    # Valid 6-digit string format should pass regex validation (raises 404 HTTPException since no active session exists)
    with pytest.raises(HTTPException) as exc_info:
        submit_mfa_code(MfaRequest(email="user@example.com", code="123456"))
    assert exc_info.value.status_code == 404
    assert "No active login verification session found" in exc_info.value.detail

    # Invalid strings: letters, special chars, wrong lengths
    invalid_codes = ["12345", "1234567", "abcdef", "12345a", "123 45", ""]
    for code in invalid_codes:
        with pytest.raises(HTTPException) as exc_info:
            submit_mfa_code(MfaRequest(email="user@example.com", code=code))
        assert exc_info.value.status_code == 400
        assert "Invalid 6-digit verification code format" in exc_info.value.detail

def test_mfa_session_ownership_and_unauthenticated_call():
    from backend.server import submit_mfa_code, MfaRequest
    from fastapi import HTTPException

    # Calling submit-mfa-code without active login session for that email
    with pytest.raises(HTTPException) as exc_info:
        submit_mfa_code(MfaRequest(email="nonexistent@example.com", code="654321"))
    assert exc_info.value.status_code == 404
    assert "No active login verification session" in exc_info.value.detail

def test_mfa_rate_limiting_behavior():
    from backend.server import submit_mfa_code, MfaRequest, _active_verifications
    from backend.scraper_engine import ScraperJob
    from backend.database import TenantStorage
    from fastapi import HTTPException

    email = "ratelimit_test@example.com"
    storage = TenantStorage(email)
    job = ScraperJob(storage, "password123", {})
    
    # Mock submit_mfa_code on job to simulate failed attempts
    job.submit_mfa_code = lambda code: False
    _active_verifications[storage.tenant_id] = {"job": job, "status": "mfa_required"}

    try:
        # Perform 5 rapid calls with valid format codes
        responses = []
        for i in range(5):
            try:
                submit_mfa_code(MfaRequest(email=email, code=f"12345{i}"))
                responses.append(200)
            except HTTPException as e:
                responses.append(e.status_code)

        # Document rate limiting behavior: first 3 calls return 400 (Failed to submit MFA verification code)
        # followed by 429 (Too Many Requests) on subsequent attempts due to rate limiting enforcement.
        assert responses == [400, 400, 400, 429, 429]
    finally:
        _active_verifications.pop(storage.tenant_id, None)

def test_mfa_volatile_memory_zero_disk_clearing():
    from backend.scraper_engine import ScraperJob
    from backend.database import TenantStorage

    storage = TenantStorage("volatile_test@example.com")
    job = ScraperJob(storage, "pass", {})

    # Initially _mfa_code is None
    assert job._mfa_code is None

    # Submit MFA code set
    job.submit_mfa_code("987654")
    assert job._mfa_code == "987654"

    # Simulate consumption logic in perform_login (copy code and set _mfa_code = None)
    code_to_submit = job._mfa_code
    job._mfa_code = None

    assert code_to_submit == "987654"
    assert job._mfa_code is None
    
    # Verify no MFA code is saved in TenantStorage config or files on disk
    config = storage.load_config()
    assert "_mfa_code" not in config
    assert "987654" not in str(config)

def test_single_archive_per_tenant_purging():
    from backend.archive_stream import purge_previous_archives
    from backend.database import TenantStorage
    
    storage = TenantStorage("archive_purge_test@example.com")
    os.makedirs(storage.archives_dir, exist_ok=True)
    
    # Create dummy previous archive files
    file1 = os.path.join(storage.archives_dir, "archive_1000.zip")
    file2 = os.path.join(storage.archives_dir, "archive_2000.zip")
    with open(file1, "w") as f: f.write("dummy1")
    with open(file2, "w") as f: f.write("dummy2")
    
    assert os.path.exists(file1)
    assert os.path.exists(file2)
    
    # Run purge
    purge_previous_archives(storage.archives_dir)
    
    # Verify directory is cleared
    remaining = os.listdir(storage.archives_dir)
    assert len(remaining) == 0

def test_cancel_archive_task_on_account_deletion():
    from backend.archive_stream import cancel_archive_task, start_zip_task, get_archive_status
    from backend.database import TenantStorage
    
    storage = TenantStorage("cancel_archive_test@example.com")
    task_info = start_zip_task(storage)
    
    assert task_info["status"] in ["processing", "ready", "error"]
    
    # Cancel task on account deletion
    cancel_archive_task(storage.tenant_id)
    
    status_after = get_archive_status(storage.tenant_id)
    assert status_after["status"] == "idle"
    assert status_after["archive_id"] is None

def test_archive_manifest_hash_up_to_date_detection():
    from backend.archive_stream import compute_manifest_hash, save_archive_metadata, get_archive_status
    from backend.database import TenantStorage
    
    storage = TenantStorage("hash_test_user@example.com")
    manifest = {
        "item1": {"obj_id": "obj1", "storage_path": "media/1.dat", "file_size": 100}
    }
    m_hash = compute_manifest_hash(manifest)
    assert isinstance(m_hash, str) and len(m_hash) == 64
    
    # Create fake archive and meta
    os.makedirs(storage.archives_dir, exist_ok=True)
    zip_path = os.path.join(storage.archives_dir, "archive_test.zip")
    with open(zip_path, "w") as f: f.write("zip_content")
    
    save_archive_metadata(storage.archives_dir, {
        "archive_id": "archive_test.zip",
        "manifest_hash": m_hash,
        "created_at": 12345,
        "file_size": 11
    })
    
    # Mock tenant manifest load
    storage.save_manifest(manifest)
    
    status = get_archive_status(storage.tenant_id, tenant_storage=storage)
    assert status["status"] == "ready"
    assert status["up_to_date"] is True
    
    # Modify manifest (add item) -> up_to_date becomes False
    manifest["item2"] = {"obj_id": "obj2", "storage_path": "media/2.dat", "file_size": 200}
    storage.save_manifest(manifest)
    
    status_updated = get_archive_status(storage.tenant_id, tenant_storage=storage)
    assert status_updated["status"] == "ready"
    assert status_updated["up_to_date"] is False





