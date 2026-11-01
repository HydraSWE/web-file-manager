"""
security/permissions.py
-----------------------
Capability-based permission system for HYDRA.

All permissions are defined here as an Enum.
Backend enforcement happens via the `require_permission` dependency
which is injected into FastAPI route handlers.

Permissions are NEVER enforced solely in JavaScript.
"""
from __future__ import annotations

import logging
from enum import Enum
from typing import List, Optional, Sequence

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Permission definitions
# ---------------------------------------------------------------------------

class Permission(str, Enum):
    # Filesystem
    FILESYSTEM_READ  = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"

    # Execution
    EXECUTION_SCRIPT  = "execution.script"
    EXECUTION_DESKTOP = "execution.desktop"

    # Process
    PROCESS_MANAGE = "process.manage"

    # System
    SYSTEM_MONITOR = "system.monitor"

    # Pairing
    PAIRING_APPROVE = "pairing.approve"

    # Future (defined now, not yet exposed in UI)
    SCREEN_VIEW    = "screen.view"
    SCREEN_CONTROL = "screen.control"
    SCREEN_CAPTURE = "screen.capture"
    SCREEN_RECORD  = "screen.record"
    AI_EXECUTE     = "ai.execute"


# Default permission set granted to owner devices
OWNER_PERMISSIONS: List[str] = [
    Permission.FILESYSTEM_READ,
    Permission.FILESYSTEM_WRITE,
    Permission.EXECUTION_SCRIPT,
    Permission.EXECUTION_DESKTOP,
    Permission.PROCESS_MANAGE,
    Permission.SYSTEM_MONITOR,
    Permission.PAIRING_APPROVE,
    # screen.control, screen.record, ai.execute NOT granted by default
    Permission.SCREEN_VIEW,
    Permission.SCREEN_CAPTURE,
]

# Permissions that require explicit owner re-confirmation before granting
SENSITIVE_PERMISSIONS: List[str] = [
    Permission.EXECUTION_SCRIPT,
    Permission.EXECUTION_DESKTOP,
    Permission.SCREEN_CONTROL,
    Permission.SCREEN_RECORD,
    Permission.AI_EXECUTE,
]

# Permissions that pending devices receive (effectively none)
PENDING_PERMISSIONS: List[str] = []


# ---------------------------------------------------------------------------
# Permission enforcement
# ---------------------------------------------------------------------------

def check_permission(device_permissions: Sequence[str], required: str) -> bool:
    """Return True if required permission is present in device_permissions."""
    return required in device_permissions


def assert_permission(device_permissions: Sequence[str], required: str) -> None:
    """
    Raise PermissionError if the required permission is not present.
    Used in non-FastAPI contexts (e.g., service layer).
    """
    if not check_permission(device_permissions, required):
        raise PermissionError(f"Permission denied: '{required}' not granted to this device")


def require_permission(required: str):
    """
    FastAPI dependency factory.
    Usage:
        @app.get("/api/fs/list")
        async def list_files(
            _: None = Depends(require_permission(Permission.FILESYSTEM_READ)),
            session = Depends(get_current_session),
        ):

    NOTE: This dependency must be composed with get_current_session.
    The session object must be attached to request.state by the auth middleware.
    """
    async def _check(request: Request) -> None:
        session = getattr(request.state, "device_session", None)
        if session is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )
        perms: List[str] = session.get("permissions", [])
        if required not in perms:
            logger.warning(
                "Permission denied: device=%s required=%s granted=%s",
                session.get("device_id", "?"),
                required,
                perms,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: '{required}' is not granted to this device",
            )
    return _check


def validate_permission_list(perms: Sequence[str]) -> List[str]:
    """
    Validate and normalise a list of permission strings.
    Returns only recognised Permission values; unknown strings are dropped.
    """
    valid = {p.value for p in Permission}
    result = []
    for p in perms:
        if p in valid:
            result.append(p)
        else:
            logger.warning("Unknown permission string ignored: %r", p)
    return list(dict.fromkeys(result))  # deduplicate while preserving order
