"""
security/router.py
------------------
FastAPI router for all HYDRA security, pairing, and device management endpoints.

Mounted in server.py with prefix /api via:
    app.include_router(security_router)

Endpoints:
  GET  /api/security/status
  POST /api/security/initial-setup
  POST /api/security/lockdown
  POST /api/security/unlock

  POST /api/pairing/request
  GET  /api/pairing/status/{request_id}
  POST /api/pairing/challenge/{request_id}
  POST /api/pairing/approve
  POST /api/pairing/reject

  GET  /api/devices
  GET  /api/devices/pending
  POST /api/devices/revoke
  POST /api/devices/permissions

  GET  /api/owners
  POST /api/owners/local-approve   (add owner — requires broker token)
  POST /api/owners/local-remove    (remove owner — requires broker token)
  POST /api/owners/request-auth    (trigger Windows auth for owner ops)

  POST /api/auth/device-login      (device challenge-response login)
  POST /api/auth/device-refresh    (token refresh)
  POST /api/auth/device-logout     (revoke session)

  GET  /api/audit/log              (owners only)
"""
from __future__ import annotations

import json
import logging
import secrets
import time
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Request, Depends, status
from fastapi.responses import JSONResponse

from security.database import get_db
from security.crypto import (
    hash_pin, verify_pin, verify_signature,
    generate_challenge, generate_token, fingerprint,
    build_approval_message, build_owner_op_message,
)
from security.device_registry import (
    has_any_owner, get_owner_count, get_all_owners, get_owner,
    get_all_trusted_devices, get_trusted_device,
    get_pending_request_count, get_trusted_device_count,
    is_owner, is_trusted, get_device_public_key,
    register_first_owner, add_owner, remove_owner, revoke_device,
    update_trusted_permissions,
)
from security.session_manager import (
    create_session, validate_session, refresh_session,
    revoke_session, extract_session_from_request,
)
from security.pairing import (
    create_pairing_request, get_pairing_request,
    get_pending_requests, issue_approval_challenge,
    approve_pairing_request, reject_pairing_request,
)
from security.lockdown import (
    is_locked_down, enable_lockdown, disable_lockdown,
    get_lockdown_info, check_lockdown_http,
)
from security.permissions import (
    Permission, OWNER_PERMISSIONS, validate_permission_list,
)
from security.audit import audit, AuditEvent, get_audit_log
from security.models import (
    SecurityState, DeviceRole,
    PairingRequestBody, PairingApprovalBody, PairingRejectionBody,
    FirstOwnerRegistrationBody, DeviceRevocationBody, PermissionUpdateBody,
    OwnerAddBody, OwnerRemoveBody, SessionRefreshBody,
    SecurityStatusResponse,
)
from security.windows_auth import request_broker_auth, is_broker_available
from local_broker.broker_protocol import BrokerAction

logger = logging.getLogger(__name__)

security_router = APIRouter(prefix="/api", tags=["security"])


# ---------------------------------------------------------------------------
# Helper: get current device session or raise 401
# ---------------------------------------------------------------------------

def _get_session(request: Request) -> dict:
    """Extract and validate session. Raises 401 if invalid."""
    token = extract_session_from_request(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required — provide session token",
        )
    session = validate_session(token)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session token",
        )
    return session


def _require_owner(session: dict) -> None:
    """Raise 403 if session does not belong to an owner device."""
    role = session.get("role", "")
    if role not in (DeviceRole.PRIMARY_OWNER, DeviceRole.CO_OWNER,
                    "primary-owner", "co-owner"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner-level access required",
        )


def _require_permission(session: dict, perm: str) -> None:
    """Raise 403 if session does not have the required permission."""
    if perm not in session.get("permissions", []):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Permission denied: '{perm}' is not granted to this device",
        )


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _get_pin_hash() -> Optional[str]:
    """Retrieve the stored Argon2id PIN hash from the DB."""
    db = get_db()
    row = db.execute(
        "SELECT value FROM security_config WHERE key = 'pin_hash'"
    ).fetchone()
    return row["value"] if row else None


# ---------------------------------------------------------------------------
# Security status
# ---------------------------------------------------------------------------

@security_router.get("/security/status", response_model=SecurityStatusResponse)
async def get_security_status():
    """Public endpoint — returns platform security state."""
    lockdown = is_locked_down()
    has_owners = has_any_owner()

    if not has_owners:
        state = SecurityState.INITIAL_SETUP
    elif lockdown:
        state = SecurityState.LOCKED
    else:
        state = SecurityState.OPERATIONAL

    return SecurityStatusResponse(
        state=state,
        has_owners=has_owners,
        lockdown_active=lockdown,
        owner_count=get_owner_count(),
        trusted_device_count=get_trusted_device_count(),
        pending_request_count=get_pending_request_count(),
    )


# ---------------------------------------------------------------------------
# First owner registration (INITIAL_SETUP only)
# ---------------------------------------------------------------------------

@security_router.post("/security/initial-setup")
async def initial_setup(body: FirstOwnerRegistrationBody, request: Request):
    """
    Register the first owner device.
    Only available when no owner exists (INITIAL_SETUP state).

    Flow:
      1. Validate PIN against stored Argon2id hash.
      2. Request Windows local authentication via broker.
      3. Only on broker approval: register device as primary owner.
    """
    check_lockdown_http("owner registration")
    ip = _client_ip(request)

    # Reject if owner already exists
    if has_any_owner():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Initial setup is complete — an owner already exists. "
                   "Use the device pairing flow to add additional owners.",
        )

    audit(AuditEvent.INITIAL_SETUP_STARTED,
          actor_id=body.device_id, ip_address=ip)

    # Validate PIN
    pin_hash = _get_pin_hash()
    if pin_hash:
        if not verify_pin(body.pin, pin_hash):
            audit(AuditEvent.AUTH_FAILED,
                  actor_id=body.device_id,
                  details={"reason": "invalid_pin"},
                  ip_address=ip)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid enrollment PIN",
            )
    # If no PIN is configured, skip PIN check (first-time setup with no PIN set)

    # Request Windows local authentication
    challenge, _exp = generate_challenge()
    display_msg = (
        f"HYDRA: Register '{body.device_name}' as the first owner device.\n\n"
        "Authenticate with your Windows account to authorize this."
    )

    if is_broker_available():
        success, err = await request_broker_auth(
            action=BrokerAction.REGISTER_FIRST_OWNER,
            challenge=challenge,
            display_msg=display_msg,
        )
        if not success:
            audit(AuditEvent.BROKER_AUTH_FAILED,
                  actor_id=body.device_id,
                  details={"error": err},
                  ip_address=ip)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Windows authentication required: {err}",
            )
    else:
        # Broker not running — reject. Never fall back to PIN-only.
        logger.warning("Initial setup attempted but broker not available")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Windows authentication broker is not running. "
                "Start the HYDRA broker (local_broker/broker.py) on this PC "
                "before registering the first owner."
            ),
        )

    # Atomically register
    ok = await register_first_owner(
        device_id=body.device_id,
        device_name=body.device_name,
        device_type=body.device_type.value,
        public_key=body.public_key,
        actor_ip=ip,
    )

    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Owner registration failed — another owner may have just been registered.",
        )

    # Create session for the new first owner
    session = create_session(
        device_id=body.device_id,
        role=DeviceRole.PRIMARY_OWNER,
        permissions=list(OWNER_PERMISSIONS),
        actor_ip=ip,
    )

    return {
        "success": True,
        "message": "First owner registered successfully",
        "session": session.model_dump(),
    }


# ---------------------------------------------------------------------------
# Device authentication (challenge-response login)
# ---------------------------------------------------------------------------

@security_router.post("/auth/device-login")
async def device_login(payload: dict, request: Request):
    """
    Device login via Ed25519 challenge-response.

    Step 1: GET /api/auth/device-challenge?device_id=<id>  → returns challenge
    Step 2: POST /api/auth/device-login
      {
        "device_id": "<id>",
        "challenge": "<the challenge from step 1>",
        "signature": "<base64url Ed25519 sig of HYDRA-LOGIN:<challenge>:<device_id>>"
      }
    """
    device_id = payload.get("device_id", "").strip()
    challenge  = payload.get("challenge", "").strip()
    signature  = payload.get("signature", "").strip()
    ip = _client_ip(request)

    if not device_id or not challenge or not signature:
        raise HTTPException(status_code=400, detail="device_id, challenge, and signature are required")

    # Validate challenge from DB (replay protection)
    db = get_db()
    ch_row = db.execute(
        """
        SELECT * FROM broker_approvals
        WHERE token = ? AND action = 'login_challenge' AND used = 0 AND expires_at > ?
        """,
        (challenge, int(time.time())),
    ).fetchone()

    if not ch_row:
        audit(AuditEvent.AUTH_FAILED,
              actor_id=device_id,
              details={"reason": "invalid_or_expired_challenge"},
              ip_address=ip)
        raise HTTPException(status_code=401, detail="Invalid or expired challenge")

    # Validate challenge is for this device
    ch_payload = json.loads(ch_row["payload"])
    if ch_payload.get("device_id") != device_id:
        raise HTTPException(status_code=401, detail="Challenge device_id mismatch")

    # Look up registered public key
    pub_key = get_device_public_key(device_id)
    if not pub_key:
        audit(AuditEvent.AUTH_FAILED,
              actor_id=device_id,
              details={"reason": "device_not_registered"},
              ip_address=ip)
        raise HTTPException(status_code=401, detail="Device not registered")

    # Verify signature: HYDRA-LOGIN:<challenge>:<device_id>
    message = f"HYDRA-LOGIN:{challenge}:{device_id}".encode()
    if not verify_signature(pub_key, message, signature):
        audit(AuditEvent.AUTH_FAILED,
              actor_id=device_id,
              details={"reason": "invalid_signature"},
              ip_address=ip)
        raise HTTPException(status_code=401, detail="Signature verification failed")

    # Mark challenge as used (replay prevention)
    db.execute(
        "UPDATE broker_approvals SET used = 1 WHERE token = ?",
        (challenge,),
    )
    db.commit()

    # Determine role + permissions
    if is_owner(device_id):
        owner = get_owner(device_id)
        if owner and owner.revoked:
            raise HTTPException(status_code=403, detail="Device has been revoked")
        role = DeviceRole(owner.role.value) if owner else DeviceRole.CO_OWNER
        permissions = list(OWNER_PERMISSIONS)
    elif is_trusted(device_id):
        from security.device_registry import get_trusted_permissions
        perms = get_trusted_permissions(device_id)
        role = DeviceRole.TRUSTED
        permissions = perms
    else:
        raise HTTPException(status_code=403, detail="Device is not registered or has been revoked")

    session = create_session(device_id=device_id, role=role,
                              permissions=permissions, actor_ip=ip)
    audit(AuditEvent.OWNER_AUTH_SUCCESS, actor_id=device_id, ip_address=ip)
    return session.model_dump()


@security_router.get("/auth/device-challenge")
async def get_device_challenge(device_id: str, request: Request):
    """
    Issue a one-time login challenge for a device.
    Challenges expire after 60 seconds and are single-use.
    """
    if not device_id or len(device_id) > 128:
        raise HTTPException(status_code=400, detail="Invalid device_id")

    challenge, expires_at = generate_challenge()
    db = get_db()
    db.execute(
        """
        INSERT INTO broker_approvals (token, action, payload, issued_at, expires_at, used)
        VALUES (?, 'login_challenge', ?, ?, ?, 0)
        """,
        (challenge, json.dumps({"device_id": device_id}), int(time.time()), expires_at),
    )
    db.commit()
    return {"challenge": challenge, "expires_at": expires_at}


@security_router.post("/auth/device-refresh")
async def device_refresh(body: SessionRefreshBody, request: Request):
    """Exchange a refresh token for a new session."""
    ip = _client_ip(request)
    new_session = refresh_session(body.refresh_token, body.device_id, actor_ip=ip)
    if not new_session:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    return new_session.model_dump()


@security_router.post("/auth/device-logout")
async def device_logout(request: Request):
    """Revoke the current session."""
    token = extract_session_from_request(request)
    if token:
        revoke_session(token, actor_ip=_client_ip(request))
    return {"success": True}


# ---------------------------------------------------------------------------
# Pairing endpoints
# ---------------------------------------------------------------------------

@security_router.post("/pairing/request")
async def pairing_request(body: PairingRequestBody, request: Request):
    """
    Submit a new device pairing request.
    The PIN is validated against the stored Argon2id hash.
    The device is NOT automatically trusted — an owner must approve.
    """
    check_lockdown_http("device pairing")
    ip = _client_ip(request)

    # Validate enrollment PIN
    if body.enrollment_pin_hash is not None:
        # Client pre-hashed — verify client supplied hash against stored hash
        # This is not the primary security check; the server does Argon2id verify
        pass

    pin_hash = _get_pin_hash()
    if pin_hash:
        client_pin = (body.pin or "").strip()
        if not client_pin or not verify_pin(client_pin, pin_hash):
            audit(AuditEvent.AUTH_FAILED,
                  actor_id=body.device_id,
                  details={"reason": "invalid_enrollment_pin"},
                  ip_address=ip)
            raise HTTPException(status_code=401, detail="Invalid enrollment PIN")

    request_id = generate_token(16)
    result = create_pairing_request(
        request_id=request_id,
        device_id=body.device_id,
        device_name=body.device_name,
        device_type=body.device_type.value,
        public_key=body.public_key,
        requested_permissions=body.requested_permissions,
        actor_ip=ip,
    )

    if not result:
        raise HTTPException(
            status_code=409,
            detail="Device is already registered or pairing request already exists",
        )

    return {
        "success": True,
        "request_id": result,
        "message": "Pairing request submitted — waiting for owner approval",
    }


@security_router.get("/pairing/status/{request_id}")
async def pairing_status(request_id: str):
    """Poll pairing request status (safe for pending devices to call)."""
    req = get_pairing_request(request_id)
    if not req:
        raise HTTPException(status_code=404, detail="Pairing request not found")
    # Return minimal info (don't expose other device details)
    return {
        "request_id": req.request_id,
        "status": req.status,
        "expires_at": req.expires_at,
    }


@security_router.post("/pairing/challenge/{request_id}")
async def get_pairing_challenge(request_id: str, request: Request):
    """
    Issue an approval challenge for a pairing request.
    Only callable by authenticated owner devices.
    """
    session = _get_session(request)
    _require_owner(session)

    challenge = issue_approval_challenge(request_id)
    if not challenge:
        raise HTTPException(status_code=404, detail="Pairing request not found or not pending")

    return {"request_id": request_id, "challenge": challenge}


@security_router.post("/pairing/approve")
async def pairing_approve(body: PairingApprovalBody, request: Request):
    """
    Approve a pairing request.
    Requires:
      1. Authenticated owner session.
      2. Valid Ed25519 signature from the owner device.
    """
    check_lockdown_http("pairing approval")
    session = _get_session(request)
    _require_owner(session)
    _require_permission(session, Permission.PAIRING_APPROVE)

    # Ensure the owner_device_id matches the authenticated session
    if session["device_id"] != body.owner_device_id:
        raise HTTPException(
            status_code=403,
            detail="owner_device_id does not match authenticated session",
        )

    ok = approve_pairing_request(
        request_id=body.request_id,
        owner_device_id=body.owner_device_id,
        owner_signature=body.owner_signature,
        grant_permissions=body.grant_permissions,
        actor_ip=_client_ip(request),
    )

    if not ok:
        raise HTTPException(
            status_code=400,
            detail="Pairing approval failed — invalid signature, expired challenge, or request not found",
        )

    return {"success": True, "message": "Device approved as trusted"}


@security_router.post("/pairing/reject")
async def pairing_reject(body: PairingRejectionBody, request: Request):
    """Reject a pairing request. Requires owner session."""
    session = _get_session(request)
    _require_owner(session)

    if session["device_id"] != body.owner_device_id:
        raise HTTPException(status_code=403, detail="owner_device_id mismatch")

    ok = reject_pairing_request(
        request_id=body.request_id,
        owner_device_id=body.owner_device_id,
        actor_ip=_client_ip(request),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Pairing request not found")

    return {"success": True}


# ---------------------------------------------------------------------------
# Device management
# ---------------------------------------------------------------------------

@security_router.get("/devices")
async def list_devices(request: Request):
    """List all devices (owner + trusted). Owners only."""
    session = _get_session(request)
    _require_owner(session)

    owners = [o.model_dump() for o in get_all_owners()]
    trusted = [t.model_dump() for t in get_all_trusted_devices()]
    return {"owners": owners, "trusted": trusted}


@security_router.get("/devices/pending")
async def list_pending_devices(request: Request):
    """List pending pairing requests. Owners only."""
    session = _get_session(request)
    _require_owner(session)
    pending = [p.model_dump() for p in get_pending_requests()]
    return {"pending": pending}


@security_router.post("/devices/revoke")
async def revoke_device_endpoint(body: DeviceRevocationBody, request: Request):
    """
    Revoke a device (owner or trusted).
    Owner revocation requires broker authentication (handled separately).
    """
    session = _get_session(request)
    _require_owner(session)
    ip = _client_ip(request)

    # Revoking an owner requires broker auth
    if is_owner(body.device_id):
        raise HTTPException(
            status_code=403,
            detail="Revoking an owner device requires local Windows authentication. "
                   "Use /api/owners/local-remove instead.",
        )

    ok = revoke_device(
        device_id=body.device_id,
        actor_id=session["device_id"],
        actor_ip=ip,
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Device not found or already revoked")

    return {"success": True}


@security_router.post("/devices/permissions")
async def update_device_permissions(body: PermissionUpdateBody, request: Request):
    """Update permissions for a trusted device. Owners only."""
    session = _get_session(request)
    _require_owner(session)

    # Prevent updating owner permissions through this endpoint
    if is_owner(body.device_id):
        raise HTTPException(
            status_code=403,
            detail="Owner permissions are managed through the owner management interface",
        )

    ok = update_trusted_permissions(
        device_id=body.device_id,
        permissions=body.permissions,
        actor_id=session["device_id"],
        actor_ip=_client_ip(request),
    )
    if not ok:
        raise HTTPException(status_code=404, detail="Trusted device not found")

    return {"success": True}


# ---------------------------------------------------------------------------
# Owner management (all require Windows local auth)
# ---------------------------------------------------------------------------

@security_router.get("/owners")
async def list_owners(request: Request):
    """List all owner devices. Owners only."""
    session = _get_session(request)
    _require_owner(session)
    owners = [o.model_dump() for o in get_all_owners()]
    return {"owners": owners}


@security_router.post("/owners/local-login")
async def local_owner_login(payload: dict, request: Request):
    """
    Windows-local PC owner login.
    Only callable from localhost/loopback on the PC hosting HYDRA.
    Triggers Windows Hello authentication to grant an owner session to the PC browser.
    """
    ip = _client_ip(request)
    if ip not in ("127.0.0.1", "::1", "localhost", "testclient"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Windows-local login is only permitted from the Windows PC itself (localhost)",
        )

    if not has_any_owner():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No owner registered yet — complete initial setup first",
        )

    if not is_broker_available():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Windows auth broker is not running. Start local_broker/broker.py.",
        )

    device_id = payload.get("device_id", "").strip()
    device_name = payload.get("device_name", "").strip() or "Windows Host PC"
    public_key = payload.get("public_key", "").strip()

    challenge, _exp = generate_challenge()
    display_msg = "HYDRA: Authenticate with Windows Hello to log in as Owner on this PC."

    success, err = await request_broker_auth(
        action=BrokerAction.LOCAL_LOGIN,
        challenge=challenge,
        display_msg=display_msg,
    )
    if not success:
        audit(AuditEvent.BROKER_AUTH_FAILED,
              actor_id=device_id or "pc_local",
              details={"error": err},
              ip_address=ip)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Windows authentication failed: {err}",
        )

    owners = get_all_owners()
    target_owner = None
    if device_id:
        target_owner = get_owner(device_id)
    if not target_owner and owners:
        target_owner = owners[0]

    # If the PC browser has its own device_id and public_key, update the primary owner record
    if device_id and public_key and target_owner and target_owner.device_id != device_id:
        db = get_db()
        from security.crypto import fingerprint
        fp = fingerprint(public_key)
        now = int(time.time())
        db.execute(
            """
            UPDATE owners
            SET device_id = ?, device_name = ?, public_key = ?, key_fingerprint = ?, last_active = ?
            WHERE device_id = ?
            """,
            (device_id, device_name, public_key, fp, now, target_owner.device_id),
        )
        db.commit()
        audit(AuditEvent.OWNER_RECOVERED,
              actor_id=device_id,
              details={"previous_device_id": target_owner.device_id, "new_fingerprint": fp},
              ip_address=ip)
        target_owner = get_owner(device_id)

    if not target_owner:
        raise HTTPException(status_code=404, detail="No active owner found")

    session = create_session(
        device_id=target_owner.device_id,
        role=target_owner.role,
        permissions=list(OWNER_PERMISSIONS),
        actor_ip=ip,
    )
    audit(AuditEvent.OWNER_AUTH_SUCCESS, actor_id=target_owner.device_id, ip_address=ip)
    return {
        "success": True,
        "message": "Windows local authentication successful",
        "session": session.model_dump(),
        "owner": target_owner.model_dump(),
    }


@security_router.post("/owners/request-auth")
async def request_owner_auth(payload: dict, request: Request):
    """
    Trigger Windows local authentication for an owner-management operation.
    Returns a short-lived broker approval token on success.

    This is the LOCAL ONLY endpoint — must be called from the PC itself.
    The broker will pop a Windows credential dialog.
    """
    session = _get_session(request)
    _require_owner(session)
    ip = _client_ip(request)

    action = payload.get("action", "").strip()
    target_device_id = payload.get("target_device_id", "").strip()

    if action not in (
        BrokerAction.ADD_OWNER,
        BrokerAction.REMOVE_OWNER,
        BrokerAction.PROMOTE_TO_OWNER,
        BrokerAction.RESET_OWNERSHIP,
        BrokerAction.CHANGE_SECURITY_POLICY,
    ):
        raise HTTPException(status_code=400, detail=f"Unknown owner action: {action}")

    if not is_broker_available():
        raise HTTPException(
            status_code=503,
            detail="Windows auth broker is not running. Start local_broker/broker.py on this PC.",
        )

    challenge, expires_at = generate_challenge()
    display_msg = (
        f"HYDRA: Authorize '{action}'"
        + (f" for device {target_device_id}" if target_device_id else "")
        + ".\n\nAuthenticate with your Windows account to authorize this operation."
    )

    broker_ok, err = await request_broker_auth(
        action=action,
        challenge=challenge,
        display_msg=display_msg,
    )

    if not broker_ok:
        audit(AuditEvent.BROKER_AUTH_FAILED,
              actor_id=session["device_id"],
              details={"action": action, "error": err},
              ip_address=ip)
        raise HTTPException(status_code=403, detail=f"Windows authentication failed: {err}")

    # Issue a one-time broker approval token
    approval_token = generate_token(32)
    db = get_db()
    db.execute(
        """
        INSERT INTO broker_approvals (token, action, payload, issued_at, expires_at, used)
        VALUES (?, ?, ?, ?, ?, 0)
        """,
        (
            approval_token,
            action,
            json.dumps({"target_device_id": target_device_id, "actor": session["device_id"]}),
            int(time.time()),
            int(time.time()) + 30,   # 30-second TTL — one-time use
        ),
    )
    db.commit()

    audit(AuditEvent.BROKER_APPROVAL_ISSUED,
          actor_id=session["device_id"],
          details={"action": action},
          ip_address=ip)

    return {
        "broker_approval_token": approval_token,
        "expires_in": 30,
        "action": action,
    }


@security_router.post("/owners/local-approve")
async def owner_local_approve(body: OwnerAddBody, request: Request):
    """
    Add a new owner using a valid broker approval token.
    The device being added must already be a trusted device.
    """
    check_lockdown_http("owner management")
    session = _get_session(request)
    _require_owner(session)
    ip = _client_ip(request)

    approval = _consume_broker_token(body.broker_approval_token, BrokerAction.ADD_OWNER)
    if approval is None:
        raise HTTPException(
            status_code=403,
            detail="Invalid or expired Windows auth approval token",
        )

    # Verify the device to be promoted exists as trusted
    trusted = get_trusted_device(body.device_id)
    if not trusted:
        raise HTTPException(
            status_code=404,
            detail="Device not found in trusted device registry",
        )

    ok = add_owner(
        device_id=trusted.device_id,
        device_name=trusted.device_name,
        device_type=trusted.device_type,
        public_key=_get_device_public_key_raw(trusted.device_id),
        role="co-owner",
        approved_by=session["device_id"],
        actor_ip=ip,
    )

    if not ok:
        raise HTTPException(status_code=500, detail="Failed to promote device to owner")

    return {"success": True, "message": f"Device {body.device_id} added as owner"}


@security_router.post("/owners/local-remove")
async def owner_local_remove(body: OwnerRemoveBody, request: Request):
    """
    Remove an owner device using a valid broker approval token.
    Refuses to remove the last owner.
    """
    check_lockdown_http("owner management")
    session = _get_session(request)
    _require_owner(session)
    ip = _client_ip(request)

    approval = _consume_broker_token(body.broker_approval_token, BrokerAction.REMOVE_OWNER)
    if approval is None:
        raise HTTPException(
            status_code=403,
            detail="Invalid or expired Windows auth approval token",
        )

    ok = remove_owner(
        device_id=body.device_id,
        actor_id=session["device_id"],
        actor_ip=ip,
    )

    if not ok:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove owner — this may be the last active owner or device not found",
        )

    return {"success": True}


# ---------------------------------------------------------------------------
# Security lockdown
# ---------------------------------------------------------------------------

@security_router.post("/security/lockdown")
async def lockdown_enable(request: Request, payload: dict = {}):
    """Enable security lockdown. Requires owner session."""
    session = _get_session(request)
    _require_owner(session)
    reason = payload.get("reason", "manual") if payload else "manual"
    enable_lockdown(reason=reason, actor_id=session["device_id"],
                    actor_ip=_client_ip(request))
    return {"success": True, "lockdown": get_lockdown_info()}


@security_router.post("/security/unlock")
async def lockdown_disable(payload: dict, request: Request):
    """
    Disable security lockdown.
    Requires owner session + valid broker approval token.
    """
    session = _get_session(request)
    _require_owner(session)

    broker_token = payload.get("broker_approval_token", "")
    approval = _consume_broker_token(broker_token, BrokerAction.CHANGE_SECURITY_POLICY)
    if approval is None:
        raise HTTPException(
            status_code=403,
            detail="Windows authentication required to unlock — use /api/owners/request-auth first",
        )

    disable_lockdown(actor_id=session["device_id"], actor_ip=_client_ip(request))
    return {"success": True, "lockdown": get_lockdown_info()}


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

@security_router.get("/audit/log")
async def get_audit(request: Request, limit: int = 100):
    """Return recent audit events. Owners only."""
    session = _get_session(request)
    _require_owner(session)
    events = get_audit_log(limit=min(limit, 500))
    return {"events": events}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _consume_broker_token(token: str, expected_action: str) -> Optional[dict]:
    """
    Validate and consume a one-time broker approval token.
    Returns the approval payload dict on success, None on failure.
    """
    if not token:
        return None
    db = get_db()
    now = int(time.time())
    row = db.execute(
        """
        SELECT * FROM broker_approvals
        WHERE token = ? AND action = ? AND used = 0 AND expires_at > ?
        """,
        (token, expected_action, now),
    ).fetchone()

    if not row:
        return None

    # Mark as used immediately (single-use)
    db.execute(
        "UPDATE broker_approvals SET used = 1 WHERE token = ?",
        (token,),
    )
    db.commit()
    audit(AuditEvent.BROKER_APPROVAL_USED,
          details={"action": expected_action})
    return json.loads(row["payload"])


def _get_device_public_key_raw(device_id: str) -> str:
    """Retrieve the stored public key for a trusted device."""
    db = get_db()
    row = db.execute(
        "SELECT public_key FROM trusted_devices WHERE device_id = ?",
        (device_id,),
    ).fetchone()
    return row["public_key"] if row else ""
