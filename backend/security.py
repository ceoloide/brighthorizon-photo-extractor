# SPDX-License-Identifier: MIT
# Security & Cryptography Module for Bright Horizons Photo Extractor
import base64
import hashlib
import hmac
import json
import os
import time
from typing import Dict, Any, Tuple, Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

DATA_DIR = os.environ.get("DATA_DIR", "/data")
SALT_FILE = os.path.join(DATA_DIR, "salt.bin")
MASTER_SECRET_FILE = os.path.join(DATA_DIR, "master_secret.bin")

def get_or_create_salt() -> bytes:
    """Ensures a persistent 32-byte salt exists for key derivation on this deployment."""
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(SALT_FILE):
        with open(SALT_FILE, "rb") as f:
            return f.read()
    salt = os.urandom(32)
    with open(SALT_FILE, "wb") as f:
        f.write(salt)
    return salt

def get_or_create_master_secret() -> bytes:
    """Gets or generates persistent master deployment secret."""
    env_secret = os.environ.get("APP_SECRET")
    if env_secret:
        return env_secret.encode("utf-8")
    
    os.makedirs(DATA_DIR, exist_ok=True)
    if os.path.exists(MASTER_SECRET_FILE):
        with open(MASTER_SECRET_FILE, "rb") as f:
            return f.read()
    secret = os.urandom(64)
    with open(MASTER_SECRET_FILE, "wb") as f:
        f.write(secret)
    return secret

def derive_aes_key(secret: bytes, salt: bytes) -> bytes:
    """Derives a 256-bit AES-GCM key using PBKDF2HMAC-SHA256."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=600000,
    )
    return kdf.derive(secret)

_SALT = get_or_create_salt()
_MASTER_SECRET = get_or_create_master_secret()
_AES_KEY = derive_aes_key(_MASTER_SECRET, _SALT)

def encrypt_bytes(data: bytes) -> str:
    """Encrypts bytes using AES-256-GCM and returns base64 string (nonce + ciphertext)."""
    aesgcm = AESGCM(_AES_KEY)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return base64.b64encode(nonce + ciphertext).decode("utf-8")

def decrypt_bytes(encrypted_b64: str) -> bytes:
    """Decrypts base64 string using AES-256-GCM."""
    raw = base64.b64decode(encrypted_b64.encode("utf-8"))
    nonce = raw[:12]
    ciphertext = raw[12:]
    aesgcm = AESGCM(_AES_KEY)
    return aesgcm.decrypt(nonce, ciphertext, None)

def encrypt_json(data: Dict[str, Any]) -> str:
    """Encrypts a JSON dictionary to base64 string."""
    json_bytes = json.dumps(data).encode("utf-8")
    return encrypt_bytes(json_bytes)

def decrypt_json(encrypted_b64: str) -> Dict[str, Any]:
    """Decrypts base64 string back to JSON dictionary."""
    json_bytes = decrypt_bytes(encrypted_b64)
    return json.loads(json_bytes.decode("utf-8"))

def get_tenant_id(email: str) -> str:
    """Generates deterministic tenant ID hash from normalized user email."""
    normalized = email.strip().lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

def create_jwt_token(email: str, tenant_id: str, expires_in: int = 86400 * 7) -> str:
    """Creates a signed JWT-like access token."""
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": tenant_id,
        "email": email,
        "iat": int(time.time()),
        "exp": int(time.time()) + expires_in
    }
    
    b64_header = base64.urlsafe_b64encode(json.dumps(header).encode()).decode().rstrip("=")
    b64_payload = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    
    signature_input = f"{b64_header}.{b64_payload}".encode("utf-8")
    signature = hmac.new(_AES_KEY, signature_input, hashlib.sha256).digest()
    b64_signature = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    
    return f"{b64_header}.{b64_payload}.{b64_signature}"

def verify_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    """Verifies a JWT token signature and expiration, returning payload if valid."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        
        b64_header, b64_payload, b64_sig = parts
        
        signature_input = f"{b64_header}.{b64_payload}".encode("utf-8")
        expected_sig = hmac.new(_AES_KEY, signature_input, hashlib.sha256).digest()
        
        # Pad signature string for b64 decode
        padded_sig = b64_sig + "=" * (-len(b64_sig) % 4)
        actual_sig = base64.urlsafe_b64decode(padded_sig)
        
        if not hmac.compare_digest(expected_sig, actual_sig):
            return None
        
        padded_payload = b64_payload + "=" * (-len(b64_payload) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded_payload).decode("utf-8"))
        
        if payload.get("exp", 0) < int(time.time()):
            return None
        
        return payload
    except Exception:
        return None
