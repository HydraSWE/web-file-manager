"""
security/device_registry.py
---------------------------
CRUD operations for the owner registry, trusted device registry,
and pending pairing requests.

All writes to the owner registry are performed inside SQLite transactions
to ensure atomicity. First-owner registration uses an explicit mutex to
prevent two simultaneous registrations.

Security invariants:
  - The last owner CANNOT be removed through this module (guarded).
  - Revocation immediately marks the device and cascades to sessions.
  - Owner operations require broker approval (enforced by callers, not here).
  - Raw public keys are never logged.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import List, Optional

from security.database import get_db
from security.crypto import fingerprint
from security.audit import audit, AuditEvent
from security.permissions import OWNER_PERMISSIONS, validate_permission_list
from security.models import (
    DeviceRole, PairingStatus,
    OwnerDevice, TrustedDevice, PendingDevice,
)

logger = logging.getLogger(__name__)

# Mutex preventing two simultaneous first-owner registrations
_first_owner_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Security state helpers
# ---------------------------------------------------------------------------

def get_owner_count() -> int:
    """Return the number of non-revoked owners."""
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) as c FROM owners WHERE revoked = 0"
    ).fetchone()
    return row["c"] if row else 0


def has_any_owner() -> bool:
    return get_owner_count() > 0


def get_trusted_device_count() -> int:
    db = get_db()
    row = db.execute(
        "SELECT COUNT(*) as c FROM trusted_devices WHERE revoked = 0"
    ).fetchone()
    return row["c"] if row else 0


def get_pending_request_count() -> int:
    db = get_db()
    now = int(time.time())
    row = db.execute(
        "SELECT COUNT(*) as c FROM pairing_requests WHERE status = 'pending' AND expires_at > ?",
        (now,),
    ).fetchone()
    return row["c"] if row else 0


# ---------------------------------------------------------------------------
# Owner registry
# ---------------------------------------------------------------------------

def get_all_owners() -> List[OwnerDevice]:
    """Return all owner devices (including revoked)."""
    db = get_db()
    rows = db.execute("SELECT * FROM owners ORDER BY registered_at ASC").fetchall()
    return [_row_to_owner(r) for r in rows]


def get_owner(device_id: str) -> Optional[OwnerDevice]:
    db = get_db()
    row = db.execute("SELECT * FROM owners WHERE device_id = ?", (device_id,)).fetchone()
    return _row_to_owner(row) if row else None


def is_owner(device_id: str) -> bool:
    db = get_db()
    row = db.execute(
        "SELECT 1 FROM owners WHERE device_id = ? AND revoked = 0",
        (device_id,),
    ).fetchone()
    return row is not None


def get_owner_public_key(device_id: str) -> Optional[str]:
    db = get_db()
    row = db.execute(
        "SELECT public_key FROM owners WHERE device_id = ? AND revoked = 0",
        (device_id,),
    ).fetchone()
    return row["public_key"] if row else None


async def register_first_owner(
    device_id: str,
    device_name: str,
    device_type: str,
    public_key: str,
    actor_ip: Optional[str] = None,
) -> bool:
    """
    Register the very first owner device.
    Protected by _first_owner_lock to prevent race conditions.
    Returns True on success, False if an owner already exists.
    """
    async with _first_owner_lock:
        if has_any_owner():
            logger.warning("First-owner registration rejected: owner already exists")
            audit(AuditEvent.INITIAL_SETUP_REJECTED,
                  actor_id=device_id,
                  details={"reason": "owner_already_exists"},
                  ip_address=actor_ip)
            return False

        db = get_db()
        now = int(time.time())
        fp = fingerprint(public_key)

        try:
            db.execute("BEGIN EXCLUSIVE")
            # Double-check inside transaction
            count = db.execute("SELECT COUNT(*) as c FROM owners WHERE revoked = 0").fetchone()["c"]
            if count > 0:
                db.execute("ROLLBACK")
                return False

            db.execute(
                """
                INSERT INTO owners
                    (device_id, device_name, device_type, role, public_key,
                     key_fingerprint, registered_at, last_active, revoked)
                VALUES (?, ?, ?, 'primary-owner', ?, ?, ?, ?, 0)
                """,
                (device_id, device_name, device_type, public_key, fp, now, now),
            )
            db.execute("COMMIT")
            logger.info("First owner registered: %s (%s)", device_name, fp)
            audit(AuditEvent.INITIAL_SETUP_COMPLETED,
                  actor_id=device_id,
                  details={"device_name": device_name, "fingerprint": fp},
                  ip_address=actor_ip)
            return True
        except Exception as e:
            db.execute("ROLLBACK")
            logger.error("Failed to register first owner: %s", e)
            return False


def add_owner(
    device_id: str,
    device_name: str,
    device_type: str,
    public_key: str,
    role: str = "co-owner",
    approved_by: Optional[str] = None,
    actor_ip: Optional[str] = None,
) -> bool:
    """
    Add an additional owner. Requires caller to have already verified
    broker authentication. Callers must enforce this — not this function.
    """
    db = get_db()
    now = int(time.time())
    fp = fingerprint(public_key)
    try:
        db.execute(
            """
            INSERT OR REPLACE INTO owners
                (device_id, device_name, device_type, role, public_key,
                 key_fingerprint, registered_at, last_active, revoked)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (device_id, device_name, device_type, role, public_key, fp, now, now),
        )
        db.commit()
        audit(AuditEvent.OWNER_REGISTERED,
              actor_id=approved_by or "system",
              target_id=device_id,
              details={"device_name": device_name, "role": role, "fingerprint": fp},
              ip_address=actor_ip)
        return True
    except Exception as e:
        logger.error("Failed to add owner: %s", e)
        return False


def remove_owner(
    device_id: str,
    actor_id: Optional[str] = None,
    actor_ip: Optional[str] = None,
) -> bool:
    """
    Remove (revoke) an owner device.
    Refuses if this is the last non-revoked owner (prevents lockout).
    """
    active_owners = [o for o in get_all_owners() if not o.revoked]
    if len(active_owners) <= 1:
        logger.warning("Refused to remove last owner: %s", device_id)
        return False

    db = get_db()
    now = int(time.time())
    try:
        db.execute(
            "UPDATE owners SET revoked = 1, revoked_at = ? WHERE device_id = ?",
            (now, device_id),
        )
        db.commit()
        # Cascade: revoke all active sessions for this owner
        _revoke_device_sessions(device_id)
        audit(AuditEvent.OWNER_REVOKED,
              actor_id=actor_id or "system",
              target_id=device_id,
              ip_address=actor_ip)
        return True
    except Exception as e:
        logger.error("Failed to remove owner %s: %s", device_id, e)
        return False


def update_owner_last_active(device_id: str) -> None:
    try:
        db = get_db()
        db.execute(
            "UPDATE owners SET last_active = ? WHERE device_id = ?",
            (int(time.time()), device_id),
        )
        db.commit()
    except Exception:
        pass


def _row_to_owner(row) -> OwnerDevice:
    now = int(time.time())
    last_act = row["last_active"]
    is_online = bool(last_act and (now - last_act < 300))
    return OwnerDevice(
        device_id=row["device_id"],
        device_name=row["device_name"],
        device_type=row["device_type"],
        role=DeviceRole(row["role"]),
        key_fingerprint=row["key_fingerprint"],
        registered_at=row["registered_at"],
        last_active=last_act,
        revoked=bool(row["revoked"]),
        revoked_at=row["revoked_at"],
        status="revoked" if row["revoked"] else ("online" if is_online else "offline"),
    )


# ---------------------------------------------------------------------------
# Trusted device registry
# ---------------------------------------------------------------------------

def get_all_trusted_devices() -> List[TrustedDevice]:
    db = get_db()
    rows = db.execute(
        "SELECT * FROM trusted_devices ORDER BY registered_at ASC"
    ).fetchall()
    return [_row_to_trusted(r) for r in rows]


def get_trusted_device(device_id: str) -> Optional[TrustedDevice]:
    db = get_db()
    row = db.execute(
        "SELECT * FROM trusted_devices WHERE device_id = ?", (device_id,)
    ).fetchone()
    return _row_to_trusted(row) if row else None


def is_trusted(device_id: str) -> bool:
    db = get_db()
    row = db.execute(
        "SELECT 1 FROM trusted_devices WHERE device_id = ? AND revoked = 0",
        (device_id,),
    ).fetchone()
    return row is not None


def get_trusted_permissions(device_id: str) -> List[str]:
    db = get_db()
    row = db.execute(
        "SELECT permissions FROM trusted_devices WHERE device_id = ? AND revoked = 0",
        (device_id,),
    ).fetchone()
    if not row:
        return []
    return json.loads(row["permissions"])


def get_device_public_key(device_id: str) -> Optional[str]:
    """Look up public key for either an owner or trusted device."""
    key = get_owner_public_key(device_id)
    if key:
        return key
    db = get_db()
    row = db.execute(
        "SELECT public_key FROM trusted_devices WHERE device_id = ? AND revoked = 0",
        (device_id,),
    ).fetchone()
    return row["public_key"] if row else None


def register_trusted_device(
    device_id: str,
    device_name: str,
    device_type: str,
    public_key: str,
    permissions: List[str],
    approved_by: str,
    actor_ip: Optional[str] = None,
) -> bool:
    db = get_db()
    now = int(time.time())
    fp = fingerprint(public_key)
    clean_perms = validate_permission_list(permissions)

    try:
        db.execute(
            """
            INSERT OR REPLACE INTO trusted_devices
                (device_id, device_name, device_type, public_key, key_fingerprint,
                 permissions, registered_at, last_active, approved_by, revoked)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (device_id, device_name, device_type, public_key, fp,
             json.dumps(clean_perms), now, now, approved_by),
        )
        db.commit()
        audit(AuditEvent.PAIRING_APPROVED,
              actor_id=approved_by,
              target_id=device_id,
              details={"device_name": device_name, "permissions": clean_perms, "fingerprint": fp},
              ip_address=actor_ip)
        return True
    except Exception as e:
        logger.error("Failed to register trusted device: %s", e)
        return False


def update_trusted_permissions(
    device_id: str,
    permissions: List[str],
    actor_id: Optional[str] = None,
    actor_ip: Optional[str] = None,
) -> bool:
    clean_perms = validate_permission_list(permissions)
    db = get_db()
    try:
        db.execute(
            "UPDATE trusted_devices SET permissions = ? WHERE device_id = ? AND revoked = 0",
            (json.dumps(clean_perms), device_id),
        )
        db.commit()
        audit(AuditEvent.DEVICE_PERMISSIONS_CHANGED,
              actor_id=actor_id,
              target_id=device_id,
              details={"new_permissions": clean_perms},
              ip_address=actor_ip)
        # Revoke existing sessions so device must re-authenticate with new perms
        _revoke_device_sessions(device_id)
        return True
    except Exception as e:
        logger.error("Failed to update permissions for %s: %s", device_id, e)
        return False


def revoke_device(
    device_id: str,
    actor_id: Optional[str] = None,
    actor_ip: Optional[str] = None,
) -> bool:
    """Revoke an owner OR trusted device (never silently ignores unknown IDs)."""
    db = get_db()
    now = int(time.time())
    rows_affected = 0

    # Try owners table
    cur = db.execute(
        "UPDATE owners SET revoked = 1, revoked_at = ? WHERE device_id = ? AND revoked = 0",
        (now, device_id),
    )
    rows_affected += cur.rowcount

    # Try trusted_devices table
    cur = db.execute(
        "UPDATE trusted_devices SET revoked = 1, revoked_at = ? WHERE device_id = ? AND revoked = 0",
        (now, device_id),
    )
    rows_affected += cur.rowcount

    if rows_affected > 0:
        db.commit()
        _revoke_device_sessions(device_id)
        audit(AuditEvent.DEVICE_REVOKED,
              actor_id=actor_id,
              target_id=device_id,
              ip_address=actor_ip)
        return True

    return False


def update_trusted_last_active(device_id: str) -> None:
    try:
        db = get_db()
        db.execute(
            "UPDATE trusted_devices SET last_active = ? WHERE device_id = ?",
            (int(time.time()), device_id),
        )
        db.commit()
    except Exception:
        pass


def _row_to_trusted(row) -> TrustedDevice:
    now = int(time.time())
    last_act = row["last_active"]
    is_online = bool(last_act and (now - last_act < 300))
    return TrustedDevice(
        device_id=row["device_id"],
        device_name=row["device_name"],
        device_type=row["device_type"],
        key_fingerprint=row["key_fingerprint"],
        permissions=json.loads(row["permissions"]),
        registered_at=row["registered_at"],
        approved_by=row["approved_by"],
        last_active=last_act,
        revoked=bool(row["revoked"]),
        status="revoked" if row["revoked"] else ("online" if is_online else "offline"),
    )


def _revoke_device_sessions(device_id: str) -> None:
    """Immediately revoke all active sessions for a device."""
    try:
        db = get_db()
        db.execute(
            "UPDATE sessions SET revoked = 1 WHERE device_id = ?",
            (device_id,),
        )
        db.commit()
    except Exception as e:
        logger.error("Failed to revoke sessions for device %s: %s", device_id, e)
