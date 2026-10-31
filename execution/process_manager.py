"""
execution/process_manager.py
-----------------------------
In-memory registry of all active and recently completed execution jobs.

Responsibilities:
  - Assign unique process IDs
  - Track PID, status, owner token, timestamps
  - Enforce max-concurrent limits
  - Handle process termination (including child processes via taskkill on Windows)
  - Maintain a bounded history of completed jobs
  - Prevent cross-user process control
"""
import os
import sys
import secrets
import time
import asyncio
import logging
from dataclasses import dataclass, field
from typing import Optional
from enum import Enum

logger = logging.getLogger(__name__)

# Maximum completed jobs to keep in history
MAX_HISTORY_SIZE = 50


class ProcessStatus(str, Enum):
    PENDING    = "pending"
    RUNNING    = "running"
    COMPLETED  = "completed"
    FAILED     = "failed"
    TERMINATED = "terminated"
    TIMEOUT    = "timeout"


@dataclass
class ExecutionRecord:
    """Immutable identity fields + mutable status fields for one execution job."""
    process_id: str          # Internal UUID-like token
    owner_token: str         # Auth token of the user who started this job
    file_path: str           # Canonical path (not logged publicly)
    filename: str            # Basename only (safe for logging)
    executor_type: str       # batch / powershell / python / exe
    mode: str                # terminal / desktop
    started_at: float        # Unix timestamp

    # Mutable — updated as process runs
    status: ProcessStatus = ProcessStatus.PENDING
    pid: Optional[int] = None
    exit_code: Optional[int] = None
    completed_at: Optional[float] = None
    error_message: Optional[str] = None

    # Internal subprocess handle (not serialised)
    _process: object = field(default=None, repr=False, compare=False)

    def to_dict(self, include_path: bool = False) -> dict:
        """Serialise to a safe dict for API responses."""
        d = {
            "process_id":    self.process_id,
            "filename":      self.filename,
            "executor_type": self.executor_type,
            "mode":          self.mode,
            "status":        self.status.value,
            "pid":           self.pid,
            "exit_code":     self.exit_code,
            "started_at":    self.started_at,
            "completed_at":  self.completed_at,
            "error_message": self.error_message,
            "duration_sec":  round((self.completed_at or time.time()) - self.started_at, 2),
        }
        if include_path:
            d["file_path"] = self.file_path
        return d


class ProcessManager:
    """
    Thread-safe (asyncio-safe) registry for all execution jobs.
    """

    def __init__(self, max_concurrent: int = 3):
        self.max_concurrent = max_concurrent
        self._active: dict[str, ExecutionRecord] = {}   # process_id -> record (pending or running)
        self._history: list[ExecutionRecord] = []         # completed jobs
        self._lock = asyncio.Lock()

    async def can_start(self) -> bool:
        async with self._lock:
            # Active dictionary tracks all pending and currently running jobs
            return len(self._active) < self.max_concurrent

    async def register(
        self,
        owner_token: str,
        file_path: str,
        filename: str,
        executor_type: str,
        mode: str,
    ) -> ExecutionRecord:
        """Create and register a new execution record. Returns the record."""
        process_id = secrets.token_urlsafe(16)
        record = ExecutionRecord(
            process_id=process_id,
            owner_token=owner_token,
            file_path=file_path,
            filename=filename,
            executor_type=executor_type,
            mode=mode,
            started_at=time.time(),
        )
        async with self._lock:
            self._active[process_id] = record
        logger.info("Registered execution job %s for file %s (mode=%s)", process_id, filename, mode)
        return record

    async def get(self, process_id: str) -> Optional[ExecutionRecord]:
        async with self._lock:
            return self._active.get(process_id)

    async def get_for_owner(self, process_id: str, owner_token: str) -> Optional[ExecutionRecord]:
        """Return record only if owned by this token (prevents cross-user access)."""
        record = await self.get(process_id)
        if record and record.owner_token == owner_token:
            return record
        return None

    async def list_active(self, owner_token: Optional[str] = None) -> list[ExecutionRecord]:
        async with self._lock:
            records = list(self._active.values())
        if owner_token:
            records = [r for r in records if r.owner_token == owner_token]
        return records

    async def get_history(self, owner_token: Optional[str] = None) -> list[ExecutionRecord]:
        async with self._lock:
            history = list(self._history)
        if owner_token:
            history = [r for r in history if r.owner_token == owner_token]
        return history

    async def mark_running(self, process_id: str, pid: int, process_handle) -> None:
        async with self._lock:
            record = self._active.get(process_id)
            if record and record.status == ProcessStatus.PENDING:
                record.status = ProcessStatus.RUNNING
                record.pid = pid
                record._process = process_handle

    async def mark_completed(self, process_id: str, exit_code: int) -> None:
        async with self._lock:
            record = self._active.pop(process_id, None)
            if record:
                if record.status == ProcessStatus.TERMINATED:
                    return
                record.status = (
                    ProcessStatus.COMPLETED if exit_code == 0
                    else ProcessStatus.FAILED
                )
                record.exit_code = exit_code
                record.completed_at = time.time()
                self._add_to_history(record)
                logger.info("Job %s completed with exit code %d", process_id, exit_code)

    async def mark_terminated(self, process_id: str) -> None:
        async with self._lock:
            record = self._active.pop(process_id, None)
            if record:
                record.status = ProcessStatus.TERMINATED
                record.completed_at = time.time()
                self._add_to_history(record)
                logger.info("Job %s terminated by user", process_id)

    async def mark_timeout(self, process_id: str) -> None:
        async with self._lock:
            record = self._active.pop(process_id, None)
            if record:
                record.status = ProcessStatus.TIMEOUT
                record.completed_at = time.time()
                self._add_to_history(record)
                logger.warning("Job %s timed out", process_id)

    async def mark_failed(self, process_id: str, error: str) -> None:
        async with self._lock:
            record = self._active.pop(process_id, None)
            if record:
                if record.status == ProcessStatus.TERMINATED:
                    return
                record.status = ProcessStatus.FAILED
                record.error_message = error
                record.completed_at = time.time()
                self._add_to_history(record)
                logger.error("Job %s failed: (error details in server log)", process_id)

    def _add_to_history(self, record: ExecutionRecord) -> None:
        """Append to history and trim if over limit. Caller must hold lock."""
        self._history.append(record)
        if len(self._history) > MAX_HISTORY_SIZE:
            self._history = self._history[-MAX_HISTORY_SIZE:]

    async def stop_process(self, process_id: str, owner_token: str) -> bool:
        """
        Terminate a running process.
        Returns True if termination was initiated, False if not found/not owned.
        Uses process-tree termination on Windows via taskkill to catch child processes.
        """
        async with self._lock:
            record = self._active.get(process_id)
            if not record:
                return False
            if record.owner_token != owner_token:
                return False
            # Transition record to terminated immediately
            record.status = ProcessStatus.TERMINATED
            record.completed_at = time.time()
            self._active.pop(process_id, None)
            self._add_to_history(record)
            pid = record.pid
            process_handle = record._process

        if pid:
            await _kill_process_tree(pid, process_handle)

        logger.info("Job %s terminated by user", process_id)
        return True


async def _kill_process_tree(pid: int, process_handle=None) -> None:
    """
    On Windows: use taskkill /F /T /PID to kill the process AND its children.
    Falls back to process_handle.terminate() if taskkill is unavailable.
    Never raises — logs errors instead.
    """
    if os.name == "nt":
        try:
            proc = await asyncio.create_subprocess_exec(
                "taskkill", "/F", "/T", "/PID", str(pid),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(proc.wait(), timeout=5.0)
            return
        except Exception as e:
            logger.warning("taskkill failed for PID %d: %s", pid, type(e).__name__)

    # Fallback: direct handle termination
    if process_handle is not None:
        try:
            if hasattr(process_handle, "terminate"):
                process_handle.terminate()
            if hasattr(process_handle, "kill"):
                process_handle.kill()
        except Exception as e:
            logger.warning("Process handle termination failed: %s", type(e).__name__)


# Singleton instance — created with defaults; manager.py overrides max_concurrent from config
process_manager = ProcessManager()
