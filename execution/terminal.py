"""
execution/terminal.py
---------------------
Async subprocess execution with real-time stdout/stderr capture.

Design:
  - No shell=True anywhere
  - Uses explicit executable paths and argument lists
  - Unicode output handled with 'replace' error mode
  - Stores output in-memory ring buffer for late WebSocket joiners
  - Supports process timeout
  - Supports graceful termination
"""
import os
import sys
import asyncio
import time
import logging
from typing import AsyncIterator, Optional

logger = logging.getLogger(__name__)

# Maximum output lines stored per process (for late WebSocket connections)
MAX_BUFFER_LINES = 5000

# Buffer size for reading from subprocess streams
STREAM_CHUNK = 4096


def _build_command(
    canonical_path: str,
    executor_type: str,
    powershell_override: bool = False,
) -> list[str]:
    """
    Build the subprocess argument list for a given executor type.

    Security invariants:
    - Never uses shell=True
    - Executable is always a known system binary or sys.executable
    - canonical_path is passed as a separate argument (no concatenation)
    - No user-supplied interpreter or arguments accepted
    - Respects system PowerShell execution policy by default
    """
    working_dir = os.path.dirname(canonical_path)

    if executor_type == "batch":
        # CMD /C runs the script and exits; /D disables AUTOEXEC.BAT processing
        return ["cmd.exe", "/D", "/C", canonical_path]

    elif executor_type == "powershell":
        # -NonInteractive: no prompts
        # System ExecutionPolicy is respected by default unless powershell_override is explicitly enabled
        cmd = ["powershell.exe", "-NonInteractive"]
        if powershell_override:
            cmd.extend(["-ExecutionPolicy", "Bypass"])
        cmd.extend(["-File", canonical_path])
        return cmd

    elif executor_type == "python":
        # Use the same interpreter running the server
        python_exe = sys.executable
        return [python_exe, canonical_path]

    else:
        raise ValueError(f"executor_type '{executor_type}' is not supported for terminal mode")


class TerminalOutputBuffer:
    """
    Thread-safe in-memory ring buffer for terminal output lines.
    Supports iteration for WebSocket streaming and late-join replay.
    """

    def __init__(self, max_lines: int = MAX_BUFFER_LINES):
        self._lines: list[dict] = []
        self._max = max_lines
        self._lock = asyncio.Lock()
        self._new_line_event = asyncio.Event()
        self._closed = False

    async def append(self, text: str, stream: str = "stdout") -> None:
        """Append a chunk of output. stream is 'stdout' or 'stderr'."""
        async with self._lock:
            self._lines.append({
                "t": time.time(),
                "s": stream,
                "d": text,
            })
            if len(self._lines) > self._max:
                self._lines = self._lines[-self._max:]
        self._new_line_event.set()
        self._new_line_event.clear()

    async def get_all(self) -> list[dict]:
        async with self._lock:
            return list(self._lines)

    def close(self) -> None:
        self._closed = True
        self._new_line_event.set()  # Wake up any waiting iterators

    async def iterate_from(self, start_index: int = 0) -> AsyncIterator[dict]:
        """
        Async generator: yields buffered lines from start_index,
        then waits for new lines until buffer is closed.
        """
        sent = start_index
        while True:
            async with self._lock:
                lines_snapshot = list(self._lines)
                is_closed = self._closed

            while sent < len(lines_snapshot):
                yield lines_snapshot[sent]
                sent += 1

            if is_closed and sent >= len(lines_snapshot):
                return

            # Wait for new data or closure
            try:
                await asyncio.wait_for(self._new_line_event.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                pass  # Loop and re-check


# Global registry of output buffers and active subprocesses, keyed by process_id
_output_buffers: dict[str, TerminalOutputBuffer] = {}
_running_subprocesses: dict[str, asyncio.subprocess.Process] = {}


def create_buffer(process_id: str) -> TerminalOutputBuffer:
    buf = TerminalOutputBuffer()
    _output_buffers[process_id] = buf
    return buf


def get_buffer(process_id: str) -> Optional[TerminalOutputBuffer]:
    return _output_buffers.get(process_id)


def remove_buffer(process_id: str) -> None:
    _output_buffers.pop(process_id, None)


async def send_stdin(process_id: str, data: str) -> bool:
    """Send data to the running subprocess's stdin stream."""
    proc = _running_subprocesses.get(process_id)
    if proc is None or proc.stdin is None or proc.stdin.is_closing():
        return False
    
    buf = get_buffer(process_id)
    if data == "^C":
        if buf:
            await buf.append("^C\n", "stderr")
        try:
            proc.terminate()
        except Exception:
            pass
        return True

    try:
        raw = data if data.endswith("\n") else data + "\n"
        proc.stdin.write(raw.encode("utf-8", errors="replace"))
        await proc.stdin.drain()
        if buf:
            await buf.append(f"> {data}\n", "stdout")
        return True
    except Exception as e:
        logger.warning("Failed to write to stdin for %s: %s", process_id, e)
        return False


async def run_terminal(
    process_id: str,
    canonical_path: str,
    executor_type: str,
    timeout_seconds: int,
    process_manager,
    powershell_override: bool = False,
) -> None:
    """
    Launch the script in terminal mode.
    Captures stdout/stderr and writes to the process's TerminalOutputBuffer.
    Updates process_manager with status and exit code.

    This coroutine runs as an asyncio background task.
    """
    buf = create_buffer(process_id)
    cmd = _build_command(canonical_path, executor_type, powershell_override=powershell_override)
    working_dir = os.path.dirname(canonical_path)

    try:
        # Launch subprocess — NO shell=True
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir,
            # On Windows: CREATE_NO_WINDOW hides the console window for captured mode
            creationflags=_get_creation_flags_for_terminal(),
        )

        _running_subprocesses[process_id] = proc
        await process_manager.mark_running(process_id, proc.pid, proc)
        await buf.append(f"[Process started — PID {proc.pid}]\n", "stdout")

        # Stream stdout and stderr concurrently
        async def drain_stream(stream: asyncio.StreamReader, stream_name: str) -> None:
            while True:
                chunk = await stream.read(STREAM_CHUNK)
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                await buf.append(text, stream_name)

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    drain_stream(proc.stdout, "stdout"),
                    drain_stream(proc.stderr, "stderr"),
                    proc.wait(),
                ),
                timeout=float(timeout_seconds),
            )
            exit_code = proc.returncode if proc.returncode is not None else -1
            await buf.append(f"\n[Process exited with code {exit_code}]\n", "stdout")
            await process_manager.mark_completed(process_id, exit_code)

        except asyncio.TimeoutError:
            await buf.append(f"\n[Process timed out after {timeout_seconds}s — terminating]\n", "stderr")
            try:
                proc.terminate()
                await asyncio.sleep(2)
                proc.kill()
            except Exception:
                pass
            await process_manager.mark_timeout(process_id)

    except Exception as e:
        safe_msg = f"[Execution error: {type(e).__name__}]"
        logger.error("Terminal execution failed for job %s: %s: %s", process_id, type(e).__name__, str(e))
        try:
            await buf.append(safe_msg + "\n", "stderr")
        except Exception:
            pass
        await process_manager.mark_failed(process_id, safe_msg)

    finally:
        _running_subprocesses.pop(process_id, None)
        buf.close()


def _get_creation_flags_for_terminal() -> int:
    """
    Windows process creation flags for captured terminal mode.
    CREATE_NO_WINDOW (0x08000000) prevents a CMD window appearing on the desktop.
    """
    if os.name == "nt":
        CREATE_NO_WINDOW = 0x08000000
        return CREATE_NO_WINDOW
    return 0
