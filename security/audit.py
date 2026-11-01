"""
security/audit.py
-----------------
Structured audit logger for HYDRA security events.

All sensitive operations (owner changes, pairing, session revocation, etc.)
are recorded here for forensic review.

Events are written to both the SQLite audit_log table and the Python logger.
The SQLite copy survives server restarts and is queryable.
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Event type constants (use these everywhere — no magic strings)
# ---------------------------------------------------------------------------

class AuditEvent:
    # Setup
    INITIAL_SETUP_STARTED   = "initial_setup.started"
    INITIAL_SETUP_COMPLETED = "initial_setup.completed"
    INITIAL_SETUP_REJECTED  = "initial_setup.rejected"

    # Owner management
    OWNER_REGISTERED       = "owner.registered"
    OWNER_REMOVED          = "owner.removed"
    OWNER_REVOKED          = "owner.revoked"
    OWNER_PROMOTED         = "owner.promoted"
    OWNER_RECOVERED        = "owner.recovered"
    OWNER_AUTH_SUCCESS     = "owner.auth_success"
    OWNER_AUTH_FAILED      = "owner.auth_failed"

    # Pairing
    PAIRING_REQUEST_CREATED  = "pairing.request_created"
    PAIRING_APPROVED         = "pairing.approved"
    PAIRING_REJECTED         = "pairing.rejected"
    PAIRING_EXPIRED          = "pairing.expired"
    PAIRING_SIG_INVALID      = "pairing.signature_invalid"

    # Sessions
    SESSION_CREATED          = "session.created"
    SESSION_REFRESHED        = "session.refreshed"
    SESSION_REVOKED          = "session.revoked"
    SESSION_EXPIRED          = "session.expired"

    # Devices
    DEVICE_REVOKED           = "device.revoked"
    DEVICE_PERMISSIONS_CHANGED = "device.permissions_changed"

    # Auth failures
    AUTH_FAILED              = "auth.failed"
    AUTH_RATE_LIMITED        = "auth.rate_limited"

    # Lockdown
    LOCKDOWN_ENABLED         = "lockdown.enabled"
    LOCKDOWN_DISABLED        = "lockdown.disabled"

    # Broker
    BROKER_APPROVAL_ISSUED   = "broker.approval_issued"
    BROKER_APPROVAL_USED     = "broker.approval_used"
    BROKER_APPROVAL_REJECTED = "broker.approval_rejected"
    BROKER_AUTH_FAILED       = "broker.auth_failed"


# ---------------------------------------------------------------------------
# Audit writer
# ---------------------------------------------------------------------------

def audit(
    event_type: str,
    actor_id: Optional[str] = None,
    target_id: Optional[str] = None,
    details: Optional[dict] = None,
    ip_address: Optional[str] = None,
) -> None:
    """
    Write an audit event to the database and the Python logger.

    This function is intentionally fire-and-forget: it will never raise
    an exception to the caller. If the DB write fails, the event is still
    logged via Python logging.

    Args:
        event_type: One of the AuditEvent constants.
        actor_id:   The device_id (or "system") initiating the action.
        target_id:  The device_id or resource being acted upon.
        details:    Optional structured dict with additional context.
        ip_address: Remote IP of the request (for network audit trails).
    """
    ts = int(time.time())
    details_json = json.dumps(details, ensure_ascii=False) if details else None

    # Always log to Python logger first (survives DB failures)
    log_parts = [f"event={event_type}"]
    if actor_id:
        log_parts.append(f"actor={actor_id}")
    if target_id:
        log_parts.append(f"target={target_id}")
    if ip_address:
        log_parts.append(f"ip={ip_address}")
    if details:
        log_parts.append(f"details={details_json}")
    logger.info("AUDIT: %s", " | ".join(log_parts))

    # Write to DB (best-effort)
    try:
        from security.database import get_db
        db = get_db()
        db.execute(
            """
            INSERT INTO audit_log (ts, event_type, actor_id, target_id, details, ip_address)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ts, event_type, actor_id, target_id, details_json, ip_address),
        )
        db.commit()
    except Exception as e:
        logger.error("Failed to write audit event to DB: %s", e)


def get_audit_log(
    limit: int = 100,
    event_type: Optional[str] = None,
    actor_id: Optional[str] = None,
) -> list:
    """
    Retrieve recent audit events from the database.
    Returns a list of dicts sorted newest-first.
    """
    try:
        from security.database import get_db
        db = get_db()
        conditions = []
        params = []

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)
        if actor_id:
            conditions.append("actor_id = ?")
            params.append(actor_id)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
        params.append(limit)

        rows = db.execute(
            f"SELECT * FROM audit_log {where} ORDER BY ts DESC LIMIT ?",
            params,
        ).fetchall()

        return [
            {
                "id": r["id"],
                "ts": r["ts"],
                "event_type": r["event_type"],
                "actor_id": r["actor_id"],
                "target_id": r["target_id"],
                "details": json.loads(r["details"]) if r["details"] else None,
                "ip_address": r["ip_address"],
            }
            for r in rows
        ]
    except Exception as e:
        logger.error("Failed to retrieve audit log: %s", e)
        return []
