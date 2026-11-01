"""
security/pairing.py
-------------------
Device pairing request lifecycle management.

Flow:
  1. New device submits PairingRequest → stored as 'pending'
  2. Owner devices are notified (via polling /api/devices/pending)
  3. Owner approves or rejects
  4. On approval: owner signature over (challenge + request_id) is verified
  5. Device is promoted to trusted_devices with granted permissions
  6. Stale pending requests are expired by _expire_old_requests()

Security:
  - Approval requires a valid owner session AND a valid Ed25519 signature
    from the owner device's registered key.
  - The approval message format is canonical (HYDRA-APPROVE:challenge:request_id)
    to prevent cross-context replay.
  - Challenges expire after 60 seconds.
  - Pairing requests expire after 15 minutes if unanswered.
  - PIN alone is never sufficient to approve pairing.
"""
from __future__ import annotations

import json
import logging
import time
from typing import List, Optional

from security.database import get_db
from security.crypto import (
    fingerprint, generate_challenge, build_approval_message, verify_signature
)
from security.audit import audit, AuditEvent
from security.permissions import validate_permission_list
from security.models import PendingDevice, PairingStatus

logger = logging.getLogger(__name__)

PAIRING_REQUEST_TTL = 15 * 60   # 15 minutes


# ---------------------------------------------------------------------------
# Create / query pairing requests
# ---------------------------------------------------------------------------

def create_pairing_request(
    request_id: str,
    device_id: str,
    device_name: str,
    device_type: str,
    public_key: str,
    requested_permissions: List[str],
    actor_ip: Optional[str] = None,
) -> Optional[str]:
    """
    Store a new pending pairing request.
    Returns the request_id on success, None on failure.

    Rejects:
      - Duplicate device IDs (device already registered or has pending request)
      - Requests when a device is already an owner or trusted device
    """
    from security.device_registry import is_owner, is_trusted

    if is_owner(device_id) or is_trusted(device_id):
        logger.warning("Pairing request rejected: device already registered: %s", device_id)
        return None

    db = get_db()
    # Check for existing active pending request for this device
    existing = db.execute(
        "SELECT request_id FROM pairing_requests WHERE device_id = ? AND status = 'pending'",
        (device_id,),
    ).fetchone()
    if existing:
        # Return the existing request ID (idempotent)
        return existing["request_id"]

    now = int(time.time())
    fp = fingerprint(public_key)
    clean_perms = validate_permission_list(requested_permissions)

    try:
        db.execute(
            """
            INSERT INTO pairing_requests
                (request_id, device_id, device_name, device_type, public_key,
                 key_fingerprint, requested_perms, created_at, expires_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            """,
            (request_id, device_id, device_name, device_type, public_key,
             fp, json.dumps(clean_perms), now, now + PAIRING_REQUEST_TTL),
        )
        db.commit()
        audit(AuditEvent.PAIRING_REQUEST_CREATED,
              actor_id=device_id,
              details={"device_name": device_name, "requested_perms": clean_perms,
                       "fingerprint": fp},
              ip_address=actor_ip)
        return request_id
    except Exception as e:
        logger.error("Failed to create pairing request: %s", e)
        return None


def get_pairing_request(request_id: str) -> Optional[PendingDevice]:
    """Return a pending pairing request by ID."""
    _expire_old_requests()
    db = get_db()
    row = db.execute(
        "SELECT * FROM pairing_requests WHERE request_id = ?",
        (request_id,),
    ).fetchone()
    return _row_to_pending(row) if row else None


def get_pending_requests() -> List[PendingDevice]:
    """Return all non-expired pending requests."""
    _expire_old_requests()
    db = get_db()
    now = int(time.time())
    rows = db.execute(
        """
        SELECT * FROM pairing_requests
        WHERE status = 'pending' AND expires_at > ?
        ORDER BY created_at DESC
        """,
        (now,),
    ).fetchall()
    return [_row_to_pending(r) for r in rows]


# ---------------------------------------------------------------------------
# Approval challenge
# ---------------------------------------------------------------------------

def issue_approval_challenge(request_id: str) -> Optional[str]:
    """
    Generate and store a short-lived approval challenge for a pairing request.
    The owner device must sign this challenge to prove it owns its private key.
    Returns the challenge string, or None if the request doesn't exist.
    """
    db = get_db()
    row = db.execute(
        "SELECT * FROM pairing_requests WHERE request_id = ? AND status = 'pending'",
        (request_id,),
    ).fetchone()
    if not row:
        return None

    challenge, expires_at = generate_challenge()
    db.execute(
        """
        UPDATE pairing_requests
        SET approval_challenge = ?, challenge_expires = ?
        WHERE request_id = ?
        """,
        (challenge, expires_at, request_id),
    )
    db.commit()
    return challenge


# ---------------------------------------------------------------------------
# Approve / reject
# ---------------------------------------------------------------------------

def approve_pairing_request(
    request_id: str,
    owner_device_id: str,
    owner_signature: str,
    grant_permissions: List[str],
    actor_ip: Optional[str] = None,
) -> bool:
    """
    Approve a pairing request.

    Verifications performed (in order):
      1. Request exists and is still pending and not expired.
      2. approving device is an active owner.
      3. Approval challenge exists and has not expired.
      4. Owner's Ed25519 signature over the canonical approval message is valid.
      5. Signature is verified against the owner's REGISTERED public key (not supplied).

    Returns True on success.
    """
    from security.device_registry import (
        is_owner, get_owner_public_key, register_trusted_device
    )

    _expire_old_requests()
    db = get_db()
    now = int(time.time())

    row = db.execute(
        "SELECT * FROM pairing_requests WHERE request_id = ? AND status = 'pending'",
        (request_id,),
    ).fetchone()

    if not row:
        logger.warning("Approval failed: request %s not found or not pending", request_id)
        return False

    if row["expires_at"] < now:
        logger.warning("Approval failed: request %s expired", request_id)
        _mark_expired(request_id)
        return False

    # Check approver is an active owner
    if not is_owner(owner_device_id):
        logger.warning("Approval failed: %s is not an active owner", owner_device_id)
        return False

    # Validate challenge
    challenge = row["approval_challenge"]
    challenge_exp = row["challenge_expires"]

    if not challenge:
        logger.warning("Approval failed: no challenge issued for request %s", request_id)
        return False

    if challenge_exp and challenge_exp < now:
        logger.warning("Approval failed: challenge expired for request %s", request_id)
        audit(AuditEvent.PAIRING_SIG_INVALID,
              actor_id=owner_device_id, target_id=request_id,
              details={"reason": "challenge_expired"})
        return False

    # Verify owner signature against registered public key (NOT the supplied key)
    owner_pubkey = get_owner_public_key(owner_device_id)
    if not owner_pubkey:
        logger.error("Approval failed: could not retrieve public key for owner %s", owner_device_id)
        return False

    message = build_approval_message(challenge, request_id)
    if not verify_signature(owner_pubkey, message, owner_signature):
        logger.warning(
            "Approval REJECTED: invalid Ed25519 signature from owner %s for request %s",
            owner_device_id, request_id
        )
        audit(AuditEvent.PAIRING_SIG_INVALID,
              actor_id=owner_device_id, target_id=request_id,
              details={"reason": "invalid_signature"},
              ip_address=actor_ip)
        return False

    # All checks passed — register as trusted device
    clean_perms = validate_permission_list(grant_permissions)
    success = register_trusted_device(
        device_id=row["device_id"],
        device_name=row["device_name"],
        device_type=row["device_type"],
        public_key=row["public_key"],
        permissions=clean_perms,
        approved_by=owner_device_id,
        actor_ip=actor_ip,
    )

    if success:
        db.execute(
            """
            UPDATE pairing_requests
            SET status = 'approved', approved_by = ?
            WHERE request_id = ?
            """,
            (owner_device_id, request_id),
        )
        db.commit()
        logger.info("Pairing approved: request=%s device=%s by owner=%s",
                    request_id, row["device_id"], owner_device_id)

    return success


def reject_pairing_request(
    request_id: str,
    owner_device_id: str,
    actor_ip: Optional[str] = None,
) -> bool:
    """Reject a pending pairing request."""
    from security.device_registry import is_owner

    if not is_owner(owner_device_id):
        return False

    db = get_db()
    row = db.execute(
        "SELECT device_id FROM pairing_requests WHERE request_id = ? AND status = 'pending'",
        (request_id,),
    ).fetchone()

    if not row:
        return False

    db.execute(
        "UPDATE pairing_requests SET status = 'rejected' WHERE request_id = ?",
        (request_id,),
    )
    db.commit()
    audit(AuditEvent.PAIRING_REJECTED,
          actor_id=owner_device_id,
          target_id=request_id,
          details={"device_id": row["device_id"]},
          ip_address=actor_ip)
    return True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _expire_old_requests() -> None:
    """Mark expired pending requests automatically."""
    try:
        db = get_db()
        now = int(time.time())
        db.execute(
            """
            UPDATE pairing_requests
            SET status = 'expired'
            WHERE status = 'pending' AND expires_at <= ?
            """,
            (now,),
        )
        db.commit()
    except Exception:
        pass


def _mark_expired(request_id: str) -> None:
    db = get_db()
    db.execute(
        "UPDATE pairing_requests SET status = 'expired' WHERE request_id = ?",
        (request_id,),
    )
    db.commit()


def _row_to_pending(row) -> PendingDevice:
    return PendingDevice(
        request_id=row["request_id"],
        device_id=row["device_id"],
        device_name=row["device_name"],
        device_type=row["device_type"],
        key_fingerprint=row["key_fingerprint"],
        requested_permissions=json.loads(row["requested_perms"]),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        status=PairingStatus(row["status"]),
    )
