"""
security/session_manager.py
---------------------------
Device-bound session management for HYDRA.

Sessions are:
  - Bound to a specific device (device_id) and its registered public key.
  - Short-lived (default: 8 hours access token, 30-day refresh token).
  - Stored in SQLite (survive restarts).
  - Revocable server-side at any time.
  - Rotating: each refresh issues a new session + new refresh token and
    revokes the old refresh token (prevents replay).

Session IDs are NOT the same as the legacy session tokens (.sessions.json).
Legacy tokens are invalidated during migration.

Security:
  - No raw PINs stored.
  - Session IDs are 32-byte cryptographically random URL-safe base64.
  - Refresh tokens are 32-byte cryptographically random URL-safe base64.
  - Sessions are validated by DB lookup on every protected request.
  - Expired or revoked sessions are rejected immediately.
"""
from __future__ import annotations

import json
import logging
import time
from typing import List, Optional

from security.database import get_db
from security.crypto import generate_token
from security.audit import audit, AuditEvent
from security.permissions import OWNER_PERMISSIONS, validate_permission_list
from security.models import DeviceSessionResponse, DeviceRole

logger = logging.getLogger(__name__)

# Session lifetimes
ACCESS_TOKEN_TTL  = 8 * 3600        # 8 hours
REFRESH_TOKEN_TTL = 30 * 24 * 3600  # 30 days


# ---------------------------------------------------------------------------
# Session creation
# ---------------------------------------------------------------------------

def create_session(
    device_id: str,
    role: DeviceRole,
    permissions: List[str],
    actor_ip: Optional[str] = None,
) -> DeviceSessionResponse:
    """
    Create a new device-bound session.
    Returns the session response object (contains access + refresh tokens).
    """
    db = get_db()
    now = int(time.time())
    session_id    = generate_token(32)
    refresh_token = generate_token(32)
    expires_at    = now + ACCESS_TOKEN_TTL
    refresh_exp   = now + REFRESH_TOKEN_TTL

    db.execute(
        """
        INSERT INTO sessions
            (session_id, device_id, issued_at, expires_at,
             refresh_token, refresh_expires, revoked)
        VALUES (?, ?, ?, ?, ?, ?, 0)
        """,
        (session_id, device_id, now, expires_at, refresh_token, refresh_exp),
    )
    db.commit()

    from security.device_registry import update_owner_last_active, update_trusted_last_active
    update_owner_last_active(device_id)
    update_trusted_last_active(device_id)

    audit(AuditEvent.SESSION_CREATED,
          actor_id=device_id,
          details={"role": role, "permissions": permissions},
          ip_address=actor_ip)

    return DeviceSessionResponse(
        session_id=session_id,
        device_id=device_id,
        expires_at=expires_at,
        refresh_token=refresh_token,
        refresh_expires=refresh_exp,
        permissions=validate_permission_list(permissions),
        role=role,
    )


# ---------------------------------------------------------------------------
# Session validation
# ---------------------------------------------------------------------------

def validate_session(session_id: str) -> Optional[dict]:
    """
    Validate a session token.

    Returns a session context dict on success:
      {
        "session_id": str,
        "device_id": str,
        "role": str,
        "permissions": List[str],
        "expires_at": int,
      }

    Returns None if the session is invalid, expired, or revoked.
    """
    if not session_id:
        return None

    db = get_db()
    row = db.execute(
        "SELECT * FROM sessions WHERE session_id = ? AND revoked = 0",
        (session_id,),
    ).fetchone()

    if not row:
        return None

    now = int(time.time())
    if row["expires_at"] < now:
        # Mark expired
        db.execute(
            "UPDATE sessions SET revoked = 1 WHERE session_id = ?",
            (session_id,),
        )
        db.commit()
        audit(AuditEvent.SESSION_EXPIRED, actor_id=row["device_id"])
        return None

    device_id = row["device_id"]
    from security.device_registry import update_owner_last_active, update_trusted_last_active
    update_owner_last_active(device_id)
    update_trusted_last_active(device_id)

    # Determine role + permissions from device registry
    role, permissions = _get_device_role_and_permissions(device_id)
    if role is None:
        # Device was revoked since session was issued
        revoke_session(session_id)
        return None

    return {
        "session_id": session_id,
        "device_id": device_id,
        "role": role,
        "permissions": permissions,
        "expires_at": row["expires_at"],
    }


def refresh_session(
    refresh_token: str,
    device_id: str,
    actor_ip: Optional[str] = None,
) -> Optional[DeviceSessionResponse]:
    """
    Exchange a refresh token for a new session + new refresh token.
    The old session and refresh token are revoked immediately.
    Returns None on invalid/expired/revoked refresh token.
    """
    db = get_db()
    now = int(time.time())

    row = db.execute(
        """
        SELECT * FROM sessions
        WHERE refresh_token = ? AND device_id = ? AND revoked = 0
        """,
        (refresh_token, device_id),
    ).fetchone()

    if not row:
        return None

    if row["refresh_expires"] < now:
        db.execute("UPDATE sessions SET revoked = 1 WHERE session_id = ?", (row["session_id"],))
        db.commit()
        audit(AuditEvent.SESSION_EXPIRED, actor_id=device_id)
        return None

    # Revoke old session atomically
    db.execute("UPDATE sessions SET revoked = 1 WHERE session_id = ?", (row["session_id"],))
    db.commit()

    # Get current device role + permissions
    role, permissions = _get_device_role_and_permissions(device_id)
    if role is None:
        return None

    audit(AuditEvent.SESSION_REFRESHED, actor_id=device_id, ip_address=actor_ip)
    return create_session(device_id, DeviceRole(role), permissions, actor_ip=actor_ip)


def revoke_session(session_id: str, actor_ip: Optional[str] = None) -> bool:
    db = get_db()
    row = db.execute(
        "SELECT device_id FROM sessions WHERE session_id = ?", (session_id,)
    ).fetchone()
    if not row:
        return False
    db.execute("UPDATE sessions SET revoked = 1 WHERE session_id = ?", (session_id,))
    db.commit()
    audit(AuditEvent.SESSION_REVOKED, actor_id=row["device_id"], ip_address=actor_ip)
    return True


def revoke_all_device_sessions(device_id: str) -> None:
    db = get_db()
    db.execute("UPDATE sessions SET revoked = 1 WHERE device_id = ?", (device_id,))
    db.commit()


# ---------------------------------------------------------------------------
# Token extraction (used in FastAPI dependencies)
# ---------------------------------------------------------------------------

def extract_session_from_request(request) -> Optional[str]:
    """
    Extract the session token from a FastAPI Request object.
    Checks: Authorization: Bearer header → X-Auth-Token header →
             cookie wfm_session → query param ?session_token
    """
    # Authorization: Bearer <token>
    auth = request.headers.get("Authorization", "").strip()
    if auth.lower().startswith("bearer "):
        t = auth[7:].strip()
        if t:
            return t

    # X-Auth-Token header
    t = request.headers.get("X-Auth-Token", "").strip()
    if t:
        return t

    # Session cookie (new cookie name; legacy wfm_token handled by migration)
    t = request.cookies.get("hydra_session", "").strip()
    if t:
        return t

    # Query param (only for WS compatibility; prefer headers)
    t = request.query_params.get("session_token", "").strip()
    if t:
        return t

    return None


# ---------------------------------------------------------------------------
# Migration: convert legacy .sessions.json to DB sessions (owner-less upgrade)
# ---------------------------------------------------------------------------

def migrate_legacy_sessions(legacy_tokens: set, config: dict) -> None:
    """
    Migrate existing plaintext session tokens to DB-backed sessions.
    Legacy tokens are marked as INVALID (devices must re-login).
    This is intentional: the new session system is device-bound.
    Also migrates the plaintext PIN to Argon2id hash.
    """
    from security.crypto import hash_pin, verify_pin
    from security.database import get_db as _db

    db = _db()
    now = int(time.time())

    # Migrate PIN
    plain_pin = config.get("pin", "").strip()
    existing_hash_row = db.execute(
        "SELECT value FROM security_config WHERE key = 'pin_hash'"
    ).fetchone()

    if plain_pin and not existing_hash_row:
        pin_hash = hash_pin(plain_pin)
        db.execute(
            "INSERT OR REPLACE INTO security_config (key, value) VALUES ('pin_hash', ?)",
            (pin_hash,),
        )
        db.commit()
        logger.info("Enrollment PIN migrated to Argon2id hash. Clear config.json pin field.")
    elif not plain_pin and not existing_hash_row:
        logger.info("No enrollment PIN configured — skipping PIN migration.")

    # Invalidate legacy tokens (log count only)
    if legacy_tokens:
        logger.info(
            "Legacy session tokens (%d) are invalidated. "
            "All devices must re-authenticate with device identity.",
            len(legacy_tokens),
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_device_role_and_permissions(device_id: str):
    """Return (role_str, permissions_list) for a device, or (None, None)."""
    from security.device_registry import is_owner, get_owner, is_trusted, get_trusted_permissions

    if is_owner(device_id):
        owner = get_owner(device_id)
        if owner and not owner.revoked:
            return owner.role.value, list(OWNER_PERMISSIONS)
        return None, None

    if is_trusted(device_id):
        perms = get_trusted_permissions(device_id)
        return DeviceRole.TRUSTED.value, perms

    return None, None
