"""
security/models.py
------------------
Pydantic v2 models for the HYDRA security subsystem.

All models used in API request / response bodies live here.
Internal dataclasses (not exposed via API) also live here for consistency.
"""
from __future__ import annotations

import time
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class DeviceRole(str, Enum):
    PRIMARY_OWNER = "primary-owner"
    CO_OWNER = "co-owner"
    TRUSTED = "trusted"
    PENDING = "pending"
    REVOKED = "revoked"


class DeviceType(str, Enum):
    PHONE = "phone"
    TABLET = "tablet"
    LAPTOP = "laptop"
    DESKTOP = "desktop"
    OTHER = "other"


class PairingStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


class SecurityState(str, Enum):
    INITIAL_SETUP = "initial_setup"   # No owner yet
    OPERATIONAL = "operational"       # Normal operation
    LOCKED = "locked"                 # Security lockdown active


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class PairingRequestBody(BaseModel):
    """Submitted by a new device attempting to pair."""
    device_id: str = Field(..., min_length=16, max_length=128)
    device_name: str = Field(..., min_length=1, max_length=64)
    device_type: DeviceType = DeviceType.OTHER
    public_key: str = Field(..., min_length=40, max_length=512,
                            description="Base64url-encoded Ed25519 public key")
    requested_permissions: List[str] = Field(default_factory=list)
    pin: Optional[str] = Field(
        None,
        description="Plaintext enrollment PIN for server-side verification"
    )
    enrollment_pin_hash: Optional[str] = Field(
        None,
        description="Client-side Argon2id hash of the enrollment PIN for verification"
    )

    @field_validator("device_id")
    @classmethod
    def device_id_safe(cls, v: str) -> str:
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("device_id may only contain alphanumerics, hyphens, and underscores")
        return v


class PairingApprovalBody(BaseModel):
    """Sent by an owner device to approve a pairing request."""
    request_id: str
    approval_challenge: str = Field(..., description="Challenge nonce issued by server")
    owner_signature: str = Field(..., description="Base64url Ed25519 signature of challenge+request_id")
    owner_device_id: str
    grant_permissions: List[str] = Field(default_factory=list)


class PairingRejectionBody(BaseModel):
    request_id: str
    owner_device_id: str


class FirstOwnerRegistrationBody(BaseModel):
    """Used only during INITIAL_SETUP state."""
    device_id: str = Field(..., min_length=16, max_length=128)
    device_name: str = Field(..., min_length=1, max_length=64)
    device_type: DeviceType = DeviceType.PHONE
    public_key: str = Field(..., min_length=40, max_length=512)
    pin: str = Field(..., min_length=4, max_length=128,
                     description="Plaintext enrollment PIN for server-side Argon2id verification")

    @field_validator("device_id")
    @classmethod
    def device_id_safe(cls, v: str) -> str:
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("device_id may only contain alphanumerics, hyphens, and underscores")
        return v


class DeviceRevocationBody(BaseModel):
    device_id: str
    reason: Optional[str] = None


class PermissionUpdateBody(BaseModel):
    device_id: str
    permissions: List[str]


class OwnerAddBody(BaseModel):
    """
    Used after broker approval is obtained.
    The device being elevated must already be a trusted device.
    """
    device_id: str
    broker_approval_token: str


class OwnerRemoveBody(BaseModel):
    device_id: str
    broker_approval_token: str


class SessionRefreshBody(BaseModel):
    refresh_token: str
    device_id: str


# ---------------------------------------------------------------------------
# Response / output models
# ---------------------------------------------------------------------------

class OwnerDevice(BaseModel):
    device_id: str
    device_name: str
    device_type: str
    role: DeviceRole
    key_fingerprint: str
    registered_at: int
    last_active: Optional[int]
    revoked: bool
    revoked_at: Optional[int]
    status: str  # "online" | "offline" | "revoked"


class TrustedDevice(BaseModel):
    device_id: str
    device_name: str
    device_type: str
    key_fingerprint: str
    permissions: List[str]
    registered_at: int
    approved_by: str
    last_active: Optional[int]
    revoked: bool
    status: str


class PendingDevice(BaseModel):
    request_id: str
    device_id: str
    device_name: str
    device_type: str
    key_fingerprint: str
    requested_permissions: List[str]
    created_at: int
    expires_at: int
    status: PairingStatus


class SecurityStatusResponse(BaseModel):
    state: SecurityState
    has_owners: bool
    lockdown_active: bool
    owner_count: int
    trusted_device_count: int
    pending_request_count: int


class DeviceSessionResponse(BaseModel):
    session_id: str
    device_id: str
    expires_at: int
    refresh_token: str
    refresh_expires: int
    permissions: List[str]
    role: DeviceRole
