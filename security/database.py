"""
security/database.py
--------------------
SQLite database initialisation, schema creation, and connection management
for the HYDRA security subsystem.

Design notes:
- Single SQLite file: hydra_security.db (next to server.py)
- WAL mode for concurrent read access
- Foreign keys enforced
- All schema migrations are additive (no destructive ALTER TABLE)
- File permissions tightened on creation (Windows ACL via icacls)
"""
import os
import sys
import sqlite3
import logging
import threading
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Resolved once at module import so all callers agree on the path
_BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = _BASE_DIR / "hydra_security.db"

# Thread-local storage for per-thread connections
_local = threading.local()

# Schema version — bump when adding new columns / tables
SCHEMA_VERSION = 1

# ---------------------------------------------------------------------------
# DDL
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

-- Schema version tracking
CREATE TABLE IF NOT EXISTS schema_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Owner device registry
CREATE TABLE IF NOT EXISTS owners (
    device_id       TEXT PRIMARY KEY,
    device_name     TEXT NOT NULL,
    device_type     TEXT NOT NULL,
    role            TEXT NOT NULL DEFAULT 'co-owner',
    public_key      TEXT NOT NULL,
    key_fingerprint TEXT NOT NULL,
    registered_at   INTEGER NOT NULL,
    last_active     INTEGER,
    revoked         INTEGER NOT NULL DEFAULT 0,
    revoked_at      INTEGER
);

-- Trusted device registry
CREATE TABLE IF NOT EXISTS trusted_devices (
    device_id       TEXT PRIMARY KEY,
    device_name     TEXT NOT NULL,
    device_type     TEXT NOT NULL,
    public_key      TEXT NOT NULL,
    key_fingerprint TEXT NOT NULL,
    permissions     TEXT NOT NULL DEFAULT '[]',
    registered_at   INTEGER NOT NULL,
    approved_by     TEXT NOT NULL,
    last_active     INTEGER,
    revoked         INTEGER NOT NULL DEFAULT 0,
    revoked_at      INTEGER
);

-- Pending pairing requests
CREATE TABLE IF NOT EXISTS pairing_requests (
    request_id          TEXT PRIMARY KEY,
    device_id           TEXT NOT NULL,
    device_name         TEXT NOT NULL,
    device_type         TEXT NOT NULL,
    public_key          TEXT NOT NULL,
    key_fingerprint     TEXT NOT NULL,
    requested_perms     TEXT NOT NULL DEFAULT '[]',
    created_at          INTEGER NOT NULL,
    expires_at          INTEGER NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    approval_challenge  TEXT,
    challenge_expires   INTEGER,
    approved_by         TEXT,
    approval_sig        TEXT
);

-- Device-bound sessions
CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,
    device_id       TEXT NOT NULL,
    issued_at       INTEGER NOT NULL,
    expires_at      INTEGER NOT NULL,
    refresh_token   TEXT NOT NULL UNIQUE,
    refresh_expires INTEGER NOT NULL,
    revoked         INTEGER NOT NULL DEFAULT 0
);

-- Security / application configuration
CREATE TABLE IF NOT EXISTS security_config (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- One-time local broker approval tokens
CREATE TABLE IF NOT EXISTS broker_approvals (
    token       TEXT PRIMARY KEY,
    action      TEXT NOT NULL,
    payload     TEXT NOT NULL,
    issued_at   INTEGER NOT NULL,
    expires_at  INTEGER NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0
);

-- Structured audit log
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,
    event_type  TEXT NOT NULL,
    actor_id    TEXT,
    target_id   TEXT,
    details     TEXT,
    ip_address  TEXT
);

-- Indexes for common lookups
CREATE INDEX IF NOT EXISTS idx_sessions_device    ON sessions(device_id);
CREATE INDEX IF NOT EXISTS idx_sessions_refresh   ON sessions(refresh_token);
CREATE INDEX IF NOT EXISTS idx_pairing_status     ON pairing_requests(status);
CREATE INDEX IF NOT EXISTS idx_audit_ts           ON audit_log(ts);
CREATE INDEX IF NOT EXISTS idx_audit_event        ON audit_log(event_type);
"""

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def init_db() -> None:
    """
    Create (or verify) the security database.
    Must be called once at server startup before any request is handled.
    Sets restrictive file permissions on Windows after creation.
    """
    db_exists = DB_PATH.exists()

    conn = _open_connection(str(DB_PATH))
    try:
        conn.executescript(_SCHEMA_SQL)
        _apply_migrations(conn)
        conn.commit()
        logger.info("Security database ready: %s", DB_PATH)
    finally:
        conn.close()

    if not db_exists:
        _restrict_db_permissions()


def get_db() -> sqlite3.Connection:
    """
    Return a per-thread SQLite connection, creating it if necessary.
    Call close_db() at the end of a request/task, or use as a context manager
    via the _DBContext helper (see below).

    Foreign keys and WAL mode are re-applied on each new connection.
    """
    if not hasattr(_local, "conn") or _local.conn is None:
        _local.conn = _open_connection(str(DB_PATH))
    return _local.conn


def close_db() -> None:
    """Close the thread-local connection (call at end of each async task)."""
    if hasattr(_local, "conn") and _local.conn is not None:
        try:
            _local.conn.close()
        except Exception:
            pass
        _local.conn = None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _open_connection(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Apply schema migrations in order. Each migration is idempotent."""
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    current = int(row["value"]) if row else 0

    if current < 1:
        # v1 baseline — already created by _SCHEMA_SQL above
        conn.execute(
            "INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', '1')"
        )
        current = 1

    # Future migrations: if current < 2: ...
    logger.debug("Schema at version %d", current)


def _restrict_db_permissions() -> None:
    """
    On Windows, restrict read/write to the current user and SYSTEM only.
    Uses icacls — silently skips on non-Windows or if icacls unavailable.
    """
    if os.name != "nt":
        return
    try:
        import subprocess
        path_str = str(DB_PATH)
        # Remove inherited permissions, grant current user full control
        subprocess.run(
            ["icacls", path_str, "/inheritance:r",
             "/grant:r", f"{os.environ.get('USERNAME', 'User')}:(F)",
             "/grant:r", "SYSTEM:(F)"],
            capture_output=True,
            timeout=5,
        )
        logger.debug("Restricted DB file permissions: %s", path_str)
    except Exception as e:
        logger.warning("Could not restrict DB permissions: %s", e)
