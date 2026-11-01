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


def _build_desktop_command(
    canonical_path: str,
    executor_type: str,
    powershell_override: bool = False,
) -> tuple[list[str] | str, int]:
    """
    Build the command line and creation flags for desktop mode.

    Returns (args, creation_flags). args may be a list or formatted command string.

    Security & Process Tracking:
    - Never uses shell=True
    - Does NOT use 'cmd.exe /C start' wrapper so the returned Popen handle tracks
      the actual interactive process / window PID directly.
    - CREATE_NEW_CONSOLE ensures visible interactive window on Windows.
    - Python paths and script paths containing spaces or metacharacters are safely quoted.
    - PowerShell respects system policy by default; bypass requires explicit powershell_override.
    """
    if executor_type == "batch":
        # Launch cmd.exe /K directly with CREATE_NEW_CONSOLE so proc tracks the console window
        return (
            ["cmd.exe", "/K", canonical_path],
            CREATE_NEW_CONSOLE,
        )

    elif executor_type == "powershell":
        # Open a new visible PowerShell console window.
        # System execution policy is respected by default unless powershell_override is explicitly set.
        cmd = ["powershell.exe", "-NoExit"]
        if powershell_override:
            cmd.extend(["-ExecutionPolicy", "Bypass"])
        cmd.extend(["-File", canonical_path])
        return (
            cmd,
            CREATE_NEW_CONSOLE,
        )

    elif executor_type == "python":
        python_exe = sys.executable
        # Use outer double quotes for cmd.exe /K to protect against cmd.exe quote-stripping
        # when both interpreter path and script path contain spaces.
        cmd_str = f'cmd.exe /K ""{python_exe}" "{canonical_path}""'
        return (
            cmd_str,
            CREATE_NEW_CONSOLE,
        )

    elif executor_type == "exe":
        # EXE: launched directly with CREATE_NEW_CONSOLE.
        # Windows creates a new console for console subsystem EXEs,
        # while Windows GUI subsystem EXEs ignore CREATE_NEW_CONSOLE and display their GUI.
        return (
            [canonical_path],
            CREATE_NEW_CONSOLE,
        )

    else:
        raise ValueError(f"executor_type '{executor_type}' is not supported for desktop mode")


def launch_desktop(
    canonical_path: str,
    executor_type: str,
    powershell_override: bool = False,
) -> subprocess.Popen:
    """
    Launch a file on the Windows desktop and return the Popen process handle.

    The returned Popen object provides:
    - The actual PID of the process / console window
    - Direct lifecycle monitoring (.poll() and .wait())
    - Safe process tree termination via taskkill

    Raises on launch failure.
    """
    if os.name != "nt":
        raise OSError("Desktop execution is only supported on Windows")

    working_dir = os.path.dirname(canonical_path) or os.getcwd()
    args, creation_flags = _build_desktop_command(
        canonical_path, executor_type, powershell_override=powershell_override
    )

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
            stdin=subprocess.DEVNULL,
        )
        return proc

    except FileNotFoundError as e:
        raise FileNotFoundError(f"Executable not found: {os.path.basename(canonical_path)}") from e
    except PermissionError as e:
        raise PermissionError("Permission denied launching executable") from e
    except Exception as e:
        logger.error("Desktop launch error for %s: %s: %s",
                     os.path.basename(canonical_path), type(e).__name__, str(e))
        raise RuntimeError(f"Desktop launch failed: {type(e).__name__}") from e
