"""
security/__init__.py
--------------------
HYDRA Security Package.

Exports the core subsystems used by server.py:
  - database  : SQLite init and connection
  - models    : Pydantic models
  - crypto    : Ed25519 / Argon2id helpers
  - permissions: Permission enum and enforcement
  - audit     : Structured audit logger
"""
from security.database import init_db, get_db
from security.permissions import Permission, OWNER_PERMISSIONS, require_permission
from security.audit import audit

__all__ = [
    "init_db",
    "get_db",
    "Permission",
    "OWNER_PERMISSIONS",
    "require_permission",
    "audit",
]
