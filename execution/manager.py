"""
execution/manager.py
--------------------
High-level execution coordinator.

Responsibilities:
  - Load and expose execution configuration
  - Validate execution requests (via validators.py)
  - Create execution jobs (via process_manager.py)
  - Dispatch to terminal.py or desktop.py
  - Enforce enabled/disabled state
  - Enforce authentication requirement
"""
import asyncio
import logging
import time
from typing import Optional

from execution.validators import validate_execution_request, get_executor_type, supports_terminal_mode
from execution.process_manager import ProcessManager, ProcessStatus, process_manager as _default_pm
from execution import terminal as terminal_mod
from execution import desktop as desktop_mod

logger = logging.getLogger(__name__)

# Default execution configuration (merged with config.json at startup)
DEFAULT_EXECUTION_CONFIG = {
    "enabled": False,
    "require_authentication": True,
    "require_confirmation": True,
    "allowed_extensions": [".bat", ".cmd", ".ps1", ".py", ".exe"],
    "default_script_mode": "terminal",
    "timeout_seconds": 300,
    "max_concurrent_processes": 3,
    "allow_desktop_execution": True,
    "allowed_roots": [],
    "powershell_override_policy": False,
}


class ExecutionManager:
    """
    Top-level coordinator for all execution operations.
    One instance is shared across the FastAPI application.
    """

    def __init__(self, config: dict, pm: Optional[ProcessManager] = None):
        self._cfg = self._build_config(config)
        self.pm = pm or _default_pm
        # Apply max_concurrent from config
        self.pm.max_concurrent = self._cfg["max_concurrent_processes"]
        logger.info(
            "ExecutionManager initialised — enabled=%s, max_concurrent=%d, allowed_roots=%s",
            self._cfg["enabled"],
            self._cfg["max_concurrent_processes"],
            self._cfg.get("allowed_roots", []),
        )

    def _build_config(self, raw_config: dict) -> dict:
        cfg = dict(DEFAULT_EXECUTION_CONFIG)
        execution_section = raw_config.get("execution", {})
        cfg.update(execution_section)
        return cfg

    @property
    def enabled(self) -> bool:
        return bool(self._cfg.get("enabled", False))

    @property
    def require_authentication(self) -> bool:
        return bool(self._cfg.get("require_authentication", True))

    @property
    def allow_desktop_execution(self) -> bool:
        return bool(self._cfg.get("allow_desktop_execution", True))

    @property
    def timeout_seconds(self) -> int:
        return int(self._cfg.get("timeout_seconds", 300))

    @property
    def allowed_extensions(self) -> list[str]:
        return self._cfg.get("allowed_extensions", [".bat", ".cmd", ".ps1", ".py", ".exe"])

    @property
    def allowed_roots(self) -> list[str]:
        return self._cfg.get("allowed_roots", [])

    @property
    def powershell_override_policy(self) -> bool:
        return bool(self._cfg.get("powershell_override_policy", False))

    def get_config_dict(self) -> dict:
        """Return safe config subset for the frontend."""
        return {
            "enabled": self.enabled,
            "require_authentication": self.require_authentication,
            "require_confirmation": self._cfg.get("require_confirmation", True),
            "allowed_extensions": self.allowed_extensions,
            "default_script_mode": self._cfg.get("default_script_mode", "terminal"),
            "timeout_seconds": self.timeout_seconds,
            "max_concurrent_processes": self._cfg.get("max_concurrent_processes", 3),
            "allow_desktop_execution": self.allow_desktop_execution,
            "allowed_roots": self.allowed_roots,
            "powershell_override_policy": self.powershell_override_policy,
        }

    def check_enabled(self) -> None:
        """Raise if execution is disabled."""
        if not self.enabled:
            raise PermissionError("File execution is disabled in configuration")

    async def start_execution(
        self,
        file_path: str,
        mode: str,
        owner_token: str,
        root_restriction: str = "",
    ) -> dict:
        """
        Validate and start execution of a file.

        Returns the execution record dict on success.
        Raises on any validation or capacity failure.
        """
        self.check_enabled()

        if mode == "desktop" and not self.allow_desktop_execution:
            raise PermissionError("Desktop execution is disabled in configuration")

        # Full path and security validation (including execution.allowed_roots)
        canonical_path, executor_type = validate_execution_request(
            file_path=file_path,
            mode=mode,
            root_restriction=root_restriction,
            allowed_extensions=self.allowed_extensions,
            allowed_roots=self.allowed_roots,
        )

        import os
        filename = os.path.basename(canonical_path)

        # Atomic capacity check & registration
        record = await self.pm.try_register(
            owner_token=owner_token,
            file_path=canonical_path,
            filename=filename,
            executor_type=executor_type,
            mode=mode,
        )

        if mode == "terminal":
            # Launch as background asyncio task
            asyncio.create_task(
                terminal_mod.run_terminal(
                    process_id=record.process_id,
                    canonical_path=canonical_path,
                    executor_type=executor_type,
                    timeout_seconds=self.timeout_seconds,
                    process_manager=self.pm,
                    powershell_override=self.powershell_override_policy,
                )
            )
            return record.to_dict()

        elif mode == "desktop":
            try:
                proc = desktop_mod.launch_desktop(
                    canonical_path,
                    executor_type,
                    powershell_override=self.powershell_override_policy,
                )
                await self.pm.mark_running(record.process_id, proc.pid, proc)
                # Background monitor task tracks the actual process lifecycle
                asyncio.create_task(
                    self._monitor_desktop_process(record.process_id, proc)
                )
                return record.to_dict()
            except Exception as e:
                await self.pm.mark_failed(record.process_id, str(type(e).__name__))
                raise

        else:
            await self.pm.unregister(record.process_id)
            raise ValueError(f"Unknown mode: {mode}")

    async def _monitor_desktop_process(self, process_id: str, proc) -> None:
        """Monitor desktop process lifecycle until exit, updating status accurately."""
        loop = asyncio.get_running_loop()
        try:
            exit_code = await loop.run_in_executor(None, proc.wait)
            await self.pm.mark_completed(process_id, exit_code)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Error monitoring desktop process %s: %s", process_id, e)
            await self.pm.mark_failed(process_id, str(type(e).__name__))

    async def stop_process(self, process_id: str, owner_token: str) -> bool:
        return await self.pm.stop_process(process_id, owner_token)

    async def get_active_processes(self, owner_token: str) -> list[dict]:
        records = await self.pm.list_active(owner_token)
        return [r.to_dict() for r in records]

    async def get_process_status(self, process_id: str, owner_token: str) -> Optional[dict]:
        record = await self.pm.get_for_owner(process_id, owner_token)
        if record:
            return record.to_dict()
        # Check history
        history = await self.pm.get_history(owner_token)
        matching = [r for r in history if r.process_id == process_id]
        return matching[0].to_dict() if matching else None

    async def get_history(self, owner_token: str) -> list[dict]:
        records = await self.pm.get_history(owner_token)
        return [r.to_dict() for r in records]

    async def send_stdin(self, process_id: str, owner_token: str, data: str) -> bool:
        """Send stdin input to a running terminal process."""
        self.check_enabled()
        record = await self.pm.get_for_owner(process_id, owner_token)
        if not record or record.mode != "terminal":
            return False
        return await terminal_mod.send_stdin(process_id, data)


# Module-level singleton — initialised in server.py after config load
execution_manager: Optional[ExecutionManager] = None


def init_execution_manager(config: dict) -> ExecutionManager:
    global execution_manager
    execution_manager = ExecutionManager(config)
    return execution_manager
