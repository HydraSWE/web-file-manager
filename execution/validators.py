"""
execution/validators.py
-----------------------
Path, extension, and security validation for the execution engine.

All validation is performed BEFORE any subprocess is created.
Uses file_ops.sanitize_path for canonical path resolution (symlink-safe).
"""
import os
import sys
from pathlib import Path


# Supported extensions and their associated interpreter category
EXECUTABLE_EXTENSIONS = {
    ".bat":  "batch",
    ".cmd":  "batch",
    ".ps1":  "powershell",
    ".py":   "python",
    ".exe":  "exe",
}

# Extensions that support browser-terminal (captured) mode
TERMINAL_CAPABLE_EXTENSIONS = {".bat", ".cmd", ".ps1", ".py"}

# Extensions that are desktop-only
DESKTOP_ONLY_EXTENSIONS = {".exe"}


def is_executable_extension(extension: str) -> bool:
    """Return True if the given file extension is in the execution allowlist."""
    return extension.lower() in EXECUTABLE_EXTENSIONS


def get_executor_type(extension: str) -> str | None:
    """Return the executor category for a file extension, or None if unsupported."""
    return EXECUTABLE_EXTENSIONS.get(extension.lower())


def supports_terminal_mode(extension: str) -> bool:
    """Return True if this extension can be run in browser-terminal capture mode."""
    return extension.lower() in TERMINAL_CAPABLE_EXTENSIONS


def validate_execution_request(
    file_path: str,
    mode: str,
    root_restriction: str,
    allowed_extensions: list[str],
) -> tuple[str, str]:
    """
    Validate a file execution request completely.

    Returns (canonical_path, executor_type) on success.
    Raises ValueError or PermissionError with a safe message on failure.

    Checks performed (in order):
    1. Path is non-empty
    2. Extension is in the configured allowlist
    3. Canonical path resolution (resolves symlinks, prevents traversal)
    4. Root restriction enforcement
    5. File exists and is a regular file (not a directory or special file)
    6. Mode is compatible with extension
    """
    if not file_path or not file_path.strip():
        raise ValueError("File path must not be empty")

    # Normalise and resolve canonical path (no symlink following for security)
    try:
        canonical = os.path.realpath(os.path.normpath(file_path))
    except Exception:
        raise ValueError("Invalid file path")

    # Enforce root restriction if configured
    if root_restriction and root_restriction.strip():
        canonical_root = os.path.realpath(os.path.normpath(root_restriction))
        if not (canonical == canonical_root or canonical.startswith(canonical_root + os.sep)):
            raise PermissionError("Access denied: path is outside the configured root boundary")

    # Extension validation — check against BOTH the static set and configured allowlist
    _, ext = os.path.splitext(canonical)
    ext = ext.lower()

    if ext not in EXECUTABLE_EXTENSIONS:
        raise ValueError(f"Extension '{ext}' is not a supported executable type")

    # Configured allowlist (from config.json) — admin may restrict further
    configured_allowed = [e.lower() for e in (allowed_extensions or [])]
    if configured_allowed and ext not in configured_allowed:
        raise ValueError(f"Extension '{ext}' is not in the configured allowed list")

    # File must exist and be a regular file
    if not os.path.exists(canonical):
        raise FileNotFoundError(f"File not found: {os.path.basename(canonical)}")

    if not os.path.isfile(canonical):
        raise ValueError("Path does not point to a regular file")

    # Validate symlink safety: realpath must still satisfy restrictions
    # (os.path.realpath already resolved any symlinks above)

    # Mode compatibility
    executor_type = EXECUTABLE_EXTENSIONS[ext]
    if mode == "terminal" and ext in DESKTOP_ONLY_EXTENSIONS:
        raise ValueError(f"Extension '{ext}' does not support terminal mode — use desktop mode")

    if mode not in ("terminal", "desktop"):
        raise ValueError(f"Unknown execution mode '{mode}' — use 'terminal' or 'desktop'")

    return canonical, executor_type


def get_python_executable() -> str:
    """
    Return the Python interpreter to use for .py script execution.
    Defaults to the currently running interpreter (sys.executable).
    This keeps the script running in the same environment as the server.
    """
    return sys.executable


def sanitize_log_path(path: str) -> str:
    """Return only the filename for safe logging — never log full paths."""
    return os.path.basename(path)
