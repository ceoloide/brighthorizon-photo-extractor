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
