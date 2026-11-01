"""
security/crypto.py
------------------
Cryptographic primitives for the HYDRA security subsystem.

Uses only established libraries — no custom cryptography.

Algorithms:
  - Ed25519  : digital signatures (device identity, owner approvals)
  - Argon2id : password / PIN hashing
  - SHA-256  : key fingerprints
  - secrets  : secure random generation for all nonces/tokens

Private keys NEVER leave this module; the server only stores public keys.
"""
from __future__ import annotations

import base64
import hashlib
import os
import secrets
import time
import logging
from typing import Optional, Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    PrivateFormat,
    NoEncryption,
)
from cryptography.exceptions import InvalidSignature

import argon2
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHashError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Argon2id configuration (OWASP recommended minimums for interactive logins)
# ---------------------------------------------------------------------------
_PH = PasswordHasher(
    time_cost=3,        # iterations
    memory_cost=65536,  # 64 MiB
    parallelism=2,
    hash_len=32,
    salt_len=16,
    encoding="utf-8",
    type=argon2.Type.ID,
)


# ---------------------------------------------------------------------------
# PIN / password hashing
# ---------------------------------------------------------------------------

def hash_pin(pin: str) -> str:
    """Return an Argon2id hash string for the given PIN."""
    return _PH.hash(pin)


def verify_pin(pin: str, stored_hash: str) -> bool:
    """
    Verify a plaintext PIN against a stored Argon2id hash.
    Returns True on match, False on mismatch.
    Never raises — all exceptions become False.
    """
    if not pin or not stored_hash:
        return False
    try:
        return _PH.verify(stored_hash, pin)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    except Exception as e:
        logger.error("Unexpected error during PIN verification: %s", type(e).__name__)
        return False


def pin_needs_rehash(stored_hash: str) -> bool:
    """Return True if the stored hash should be upgraded (parameters changed)."""
    try:
        return _PH.check_needs_rehash(stored_hash)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Ed25519 key operations
# ---------------------------------------------------------------------------

def generate_server_keypair() -> Tuple[bytes, bytes]:
    """
    Generate a new Ed25519 key pair for the local broker.
    Returns (private_key_bytes_raw, public_key_bytes_raw).
    The private key bytes should be stored in a protected file, NOT in the DB.
    """
    private_key = Ed25519PrivateKey.generate()
    priv_bytes = private_key.private_bytes(
        encoding=Encoding.Raw,
        format=PrivateFormat.Raw,
        encryption_algorithm=NoEncryption(),
    )
    pub_bytes = private_key.public_key().public_bytes(
        encoding=Encoding.Raw,
        format=PublicFormat.Raw,
    )
    return priv_bytes, pub_bytes


def public_key_to_b64(pub_bytes: bytes) -> str:
    """Encode raw 32-byte Ed25519 public key as base64url (no padding)."""
    return base64.urlsafe_b64encode(pub_bytes).rstrip(b"=").decode()


def b64_to_public_key(b64_str: str) -> Ed25519PublicKey:
    """Decode a base64url public key string into an Ed25519PublicKey object."""
    # Add padding if necessary
    padded = b64_str + "=" * (-len(b64_str) % 4)
    raw = base64.urlsafe_b64decode(padded)
    if len(raw) != 32:
        raise ValueError(f"Invalid Ed25519 public key length: {len(raw)} (expected 32)")
    return Ed25519PublicKey.from_public_bytes(raw)


def verify_signature(
    public_key_b64: str,
    message: bytes,
    signature_b64: str,
) -> bool:
    """
    Verify an Ed25519 signature.

    Args:
        public_key_b64: Base64url-encoded raw 32-byte public key.
        message:        The exact bytes that were signed.
        signature_b64: Base64url-encoded 64-byte signature.

    Returns True on valid signature, False on any failure.
    """
    try:
        pub_key = b64_to_public_key(public_key_b64)
        padded_sig = signature_b64 + "=" * (-len(signature_b64) % 4)
        sig_bytes = base64.urlsafe_b64decode(padded_sig)
        pub_key.verify(sig_bytes, message)
        return True
    except InvalidSignature:
        return False
    except Exception as e:
        logger.warning("Signature verification error: %s", type(e).__name__)
        return False


def fingerprint(public_key_b64: str) -> str:
    """
    Compute a short SHA-256 fingerprint of a base64url public key.
    Format: first 16 hex chars of SHA-256(raw_public_key_bytes).
    Example: "a3f2c1d0e8b74f9a"
    """
    try:
        padded = public_key_b64 + "=" * (-len(public_key_b64) % 4)
        raw = base64.urlsafe_b64decode(padded)
        digest = hashlib.sha256(raw).hexdigest()
        return digest[:16]
    except Exception:
        return "invalid"


# ---------------------------------------------------------------------------
# Secure random token generation
# ---------------------------------------------------------------------------

def generate_token(nbytes: int = 32) -> str:
    """Generate a cryptographically secure URL-safe base64 token."""
    return secrets.token_urlsafe(nbytes)


def generate_nonce(nbytes: int = 32) -> bytes:
    """Generate a cryptographically secure random nonce (raw bytes)."""
    return secrets.token_bytes(nbytes)


def generate_challenge() -> Tuple[str, int]:
    """
    Generate a short-lived challenge nonce for owner operations.
    Returns (challenge_b64url, expiry_unix_timestamp).
    Challenges expire after 60 seconds.
    """
    raw = generate_nonce(32)
    b64 = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    expires = int(time.time()) + 60
    return b64, expires


def build_approval_message(challenge: str, request_id: str) -> bytes:
    """
    Build the canonical bytes an owner device must sign to approve a pairing.
    Format: b"HYDRA-APPROVE:" + challenge.encode() + b":" + request_id.encode()
    This prevents cross-context replay of signatures.
    """
    return b"HYDRA-APPROVE:" + challenge.encode() + b":" + request_id.encode()


def build_owner_op_message(challenge: str, action: str) -> bytes:
    """
    Build the canonical bytes the broker signs for an owner-management operation.
    Format: b"HYDRA-OWNER-OP:" + action.encode() + b":" + challenge.encode()
    """
    return b"HYDRA-OWNER-OP:" + action.encode() + b":" + challenge.encode()
