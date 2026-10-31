"""
execution/desktop.py
--------------------
Windows desktop process launching for scripts and executables.

Desktop mode opens a VISIBLE console or GUI window on the user's desktop.
The server runs in the same interactive Windows session (started via run.bat),
so subprocess.Popen can display windows directly — no service/broker needed.

Design:
  - No shell=True
  - Explicit executable paths only
  - Working directory preserved
  - Windows process creation flags used correctly
  - GUI and console applications both supported
"""
import os
import sys
import subprocess
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Windows process creation flags
CREATE_NEW_CONSOLE = 0x00000010      # Opens in a new visible console window
DETACHED_PROCESS   = 0x00000008      # No inherited console (for GUI apps)


def _build_desktop_command(canonical_path: str, executor_type: str) -> tuple[list[str], int]:
    """
    Build the command line and creation flags for desktop mode.

    Returns (args_list, creation_flags).

    Security:
    - No shell=True
    - No user-supplied interpreter or arguments
    - sys.executable for Python scripts (same environment as server)
    """
    if executor_type == "batch":
        # Open a new CMD console window; /K keeps the window open after the script exits
        # so the user can read the output. The script path is a single argument.
        return (
            ["cmd.exe", "/C", "start", "cmd.exe", "/K", canonical_path],
            CREATE_NEW_CONSOLE,
        )

    elif executor_type == "powershell":
        # Open a new PowerShell window. -NoExit keeps it open after the script finishes.
        return (
            [
                "powershell.exe",
                "-NoExit",
                "-ExecutionPolicy", "Bypass",
                "-File", canonical_path,
            ],
            CREATE_NEW_CONSOLE,
        )

    elif executor_type == "python":
        python_exe = sys.executable
        # For desktop Python: open a CMD window that runs python and keeps it open
        return (
            ["cmd.exe", "/C", "start", "cmd.exe", "/K", python_exe, canonical_path],
            CREATE_NEW_CONSOLE,
        )

    elif executor_type == "exe":
        # EXE: launch directly. GUI apps get DETACHED_PROCESS so they don't
        # inherit the server's console (which would be invisible or confusing).
        return (
            [canonical_path],
            DETACHED_PROCESS,
        )

    else:
        raise ValueError(f"executor_type '{executor_type}' is not supported for desktop mode")


def launch_desktop(
    canonical_path: str,
    executor_type: str,
) -> tuple[int, str]:
    """
    Launch a file on the Windows desktop.

    Returns (pid, status_message).
    Raises on failure.

    The server process runs in the user's interactive session (via run.bat),
    so the launched window will appear on the desktop.
    """
    if os.name != "nt":
        raise OSError("Desktop execution is only supported on Windows")

    working_dir = os.path.dirname(canonical_path) or os.getcwd()
    args, creation_flags = _build_desktop_command(canonical_path, executor_type)

    logger.info(
        "Desktop launch: executor=%s, file=%s, flags=0x%X",
        executor_type,
        os.path.basename(canonical_path),
        creation_flags,
    )

    try:
        proc = subprocess.Popen(
            args,
            cwd=working_dir,
            creationflags=creation_flags,
            # No stdin/stdout/stderr redirection — desktop window handles its own I/O
            stdin=subprocess.DEVNULL,
            # Do NOT set stdout/stderr — that would suppress the window output
        )
        pid = proc.pid
        return pid, f"Launched on desktop (PID {pid})"

    except FileNotFoundError as e:
        raise FileNotFoundError(f"Executable not found: {os.path.basename(canonical_path)}") from e
    except PermissionError as e:
        raise PermissionError("Permission denied launching executable") from e
    except Exception as e:
        logger.error("Desktop launch error for %s: %s: %s",
                     os.path.basename(canonical_path), type(e).__name__, str(e))
        raise RuntimeError(f"Desktop launch failed: {type(e).__name__}") from e
