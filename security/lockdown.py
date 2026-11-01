"""
security/lockdown.py
--------------------
Security lockdown state machine for HYDRA.

When lockdown is active:
  - New device pairing is blocked
  - New owner registration is blocked
  - Owner registry changes are blocked
  - Script execution is blocked
  - Desktop execution is blocked
  - Future screen control is blocked

Existing trusted-device behavior follows the host-configured policy
(default: existing sessions continue but no new sensitive ops).

Lockdown state is persisted in the security_config table so it
survives server restarts.

Lockdown can be triggered:
  1. Manually via /api/security/lockdown (requires owner auth)
  2. Automatically when the Windows workstation locks (future hook)
  3. Automatically after configured inactivity period

Unlock requires:
  1. Owner session + broker authentication (Windows local auth)
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from security.database import get_db
from security.audit import audit, AuditEvent

logger = logging.getLogger(__name__)

# Security config keys
_KEY_LOCKDOWN_ACTIVE = "lockdown_active"
_KEY_LOCKDOWN_SINCE  = "lockdown_since"
_KEY_LOCKDOWN_REASON = "lockdown_reason"


# ---------------------------------------------------------------------------
# Lockdown state
# ---------------------------------------------------------------------------

def is_locked_down() -> bool:
    """Return True if security lockdown is currently active."""
    db = get_db()
    row = db.execute(
        "SELECT value FROM security_config WHERE key = ?",
        (_KEY_LOCKDOWN_ACTIVE,),
    ).fetchone()
    return row is not None and row["value"] == "1"


def enable_lockdown(
    reason: str = "manual",
    actor_id: Optional[str] = None,
    actor_ip: Optional[str] = None,
) -> None:
    """
    Enable security lockdown.
    Idempotent — safe to call when already locked.
    """
    db = get_db()
    now = str(int(time.time()))
    db.execute(
        "INSERT OR REPLACE INTO security_config (key, value) VALUES (?, '1')",
        (_KEY_LOCKDOWN_ACTIVE,),
    )
    db.execute(
        "INSERT OR REPLACE INTO security_config (key, value) VALUES (?, ?)",
        (_KEY_LOCKDOWN_SINCE, now),
    )
    db.execute(
        "INSERT OR REPLACE INTO security_config (key, value) VALUES (?, ?)",
        (_KEY_LOCKDOWN_REASON, reason),
    )
    db.commit()
    logger.warning("HYDRA LOCKDOWN ENABLED — reason=%s actor=%s", reason, actor_id)
    audit(AuditEvent.LOCKDOWN_ENABLED,
          actor_id=actor_id or "system",
          details={"reason": reason},
          ip_address=actor_ip)


def disable_lockdown(
    actor_id: Optional[str] = None,
    actor_ip: Optional[str] = None,
) -> None:
    """
    Disable security lockdown.
    Requires caller to have already verified broker authentication.
    """
    db = get_db()
    db.execute(
        "INSERT OR REPLACE INTO security_config (key, value) VALUES (?, '0')",
        (_KEY_LOCKDOWN_ACTIVE,),
    )
    db.commit()
    logger.info("HYDRA lockdown disabled by %s", actor_id)
    audit(AuditEvent.LOCKDOWN_DISABLED,
          actor_id=actor_id or "system",
          ip_address=actor_ip)


def get_lockdown_info() -> dict:
    """Return current lockdown state and metadata."""
    db = get_db()

    def _val(key: str) -> Optional[str]:
        row = db.execute(
            "SELECT value FROM security_config WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else None

    active = _val(_KEY_LOCKDOWN_ACTIVE) == "1"
    since_str = _val(_KEY_LOCKDOWN_SINCE)
    reason = _val(_KEY_LOCKDOWN_REASON)

    return {
        "active": active,
        "since": int(since_str) if since_str else None,
        "reason": reason,
    }


# ---------------------------------------------------------------------------
# Enforcement helpers (called by FastAPI dependencies)
# ---------------------------------------------------------------------------

def assert_not_locked_down(operation: str = "this operation") -> None:
    """
    Raise a PermissionError if lockdown is active.
    Used in service-layer code (non-FastAPI contexts).
    """
    if is_locked_down():
        raise PermissionError(
            f"Security lockdown is active — {operation} is blocked. "
            "Contact the PC owner to unlock."
        )


def check_lockdown_http(operation: str = "this operation") -> None:
    """
    Raise an HTTPException 503 if lockdown is active.
    Used in FastAPI route handlers.
    """
    if is_locked_down():
        from fastapi import HTTPException, status
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                f"Security lockdown is active — {operation} is blocked. "
                "Contact the PC owner to unlock."
            ),
        )
