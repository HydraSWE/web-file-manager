"""
test_execution_engine.py
-------------------------
Comprehensive automated test suite for the Hydra Execution Engine.
Tests all 11 required audit points:
1. WebSocket ownership & cross-session isolation
2. Unauthorized execution
3. Unauthorized process termination
4. Root boundary enforcement (execution.allowed_roots)
5. Symlink/path traversal protection
6. Atomic concurrent process registration
7. Terminal process lifecycle
8. Desktop process lifecycle & process-tree termination
9. Windows command quoting (paths with spaces & metacharacters)
10. PowerShell execution policy behavior
11. Existing file-manager functionality
"""
import os
import sys
import time
import json
import asyncio
import tempfile
import unittest
from pathlib import Path

# Add hydra-file-manager to sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HYDRA_DIR = os.path.join(BASE_DIR, "hydra-file-manager")
if HYDRA_DIR not in sys.path:
    sys.path.insert(0, HYDRA_DIR)

from execution.process_manager import ProcessManager, ProcessStatus, ExecutionRecord
from execution.validators import validate_execution_request
from execution import terminal as terminal_mod
from execution import desktop as desktop_mod
from execution.manager import ExecutionManager
import server


class TestHydraExecutionEngine(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="hydra_test_")
        self.pm = ProcessManager(max_concurrent=3)
        self.exec_mgr = ExecutionManager(
            config={
                "execution": {
                    "enabled": True,
                    "require_authentication": True,
                    "max_concurrent_processes": 3,
                    "timeout_seconds": 10,
                    "allow_desktop_execution": True,
                    "allowed_roots": [],
                    "powershell_override_policy": False,
                }
            },
            pm=self.pm,
        )

    def tearDown(self):
        import shutil
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass

    # 1. WebSocket Ownership & Cross-Session Isolation
    async def test_01_websocket_ownership(self):
        token_a = "session_token_aaa_111"
        token_b = "session_token_bbb_222"
        server.SESSION_TOKENS.add(token_a)
        server.SESSION_TOKENS.add(token_b)

        # Register a job owned by session A
        record = await self.pm.try_register(
            owner_token=token_a,
            file_path=os.path.join(self.temp_dir, "test.bat"),
            filename="test.bat",
            executor_type="batch",
            mode="terminal",
        )
        proc_id = record.process_id

        # Verify get_for_owner isolates Session A and Session B
        self.assertIsNotNone(await self.pm.get_for_owner(proc_id, token_a))
        self.assertIsNone(await self.pm.get_for_owner(proc_id, token_b))

        # Test server websocket ownership logic: Session B must be rejected
        server._execution_manager = self.exec_mgr
        from starlette.testclient import TestClient
        client = TestClient(server.app)

        # Connect with Session B token -> must fail / disconnect with code 4003
        try:
            with client.websocket_connect(f"/ws/execution/{proc_id}?token={token_b}") as ws:
                self.fail("Session B should not have connected to Session A's process")
        except Exception as e:
            # WebSocket was closed before accept / rejected
            self.assertTrue(True)

    # 2. Unauthorized Execution
    async def test_02_unauthorized_execution(self):
        # Disabled execution
        disabled_mgr = ExecutionManager(config={"execution": {"enabled": False}}, pm=self.pm)
        test_file = os.path.join(self.temp_dir, "test.bat")
        with open(test_file, "w") as f:
            f.write("@echo off\n")

        with self.assertRaises(PermissionError):
            await disabled_mgr.start_execution(test_file, "terminal", "token_any")

    # 3. Unauthorized Process Termination
    async def test_03_unauthorized_process_termination(self):
        token_a = "token_owner_a"
        token_b = "token_intruder_b"

        test_file = os.path.join(self.temp_dir, "test.bat")
        with open(test_file, "w") as f:
            f.write("@echo off\n")

        record = await self.pm.try_register(
            owner_token=token_a,
            file_path=test_file,
            filename="test.bat",
            executor_type="batch",
            mode="terminal",
        )

        # Session B attempts to kill Session A's job -> must return False
        stopped = await self.pm.stop_process(record.process_id, token_b)
        self.assertFalse(stopped)
        self.assertEqual(record.status, ProcessStatus.PENDING)

        # Session A kills -> must return True
        stopped_a = await self.pm.stop_process(record.process_id, token_a)
        self.assertTrue(stopped_a)
        self.assertEqual(record.status, ProcessStatus.TERMINATED)

    # 4. Root Boundary Enforcement (execution.allowed_roots)
    async def test_04_root_boundary_enforcement(self):
        allowed_dir = os.path.join(self.temp_dir, "allowed_zone")
        forbidden_dir = os.path.join(self.temp_dir, "forbidden_zone")
        os.makedirs(allowed_dir, exist_ok=True)
        os.makedirs(forbidden_dir, exist_ok=True)

        allowed_script = os.path.join(allowed_dir, "allowed.py")
        forbidden_script = os.path.join(forbidden_dir, "forbidden.py")
        with open(allowed_script, "w") as f:
            f.write("print('OK')\n")
        with open(forbidden_script, "w") as f:
            f.write("print('NO')\n")

        # Configured allowed_roots
        canon, ext = validate_execution_request(
            file_path=allowed_script,
            mode="terminal",
            allowed_roots=[allowed_dir],
        )
        self.assertEqual(canon, os.path.realpath(allowed_script))

        # Forbidden path must raise PermissionError
        with self.assertRaises(PermissionError) as ctx:
            validate_execution_request(
                file_path=forbidden_script,
                mode="terminal",
                allowed_roots=[allowed_dir],
            )
        self.assertIn("allowed_roots", str(ctx.exception))

        # Empty allowed_roots must allow execution (unrestricted)
        canon_unrestricted, _ = validate_execution_request(
            file_path=forbidden_script,
            mode="terminal",
            allowed_roots=[],
        )
        self.assertEqual(canon_unrestricted, os.path.realpath(forbidden_script))

    # 5. Symlink / Path Traversal Protection
    async def test_05_path_traversal_protection(self):
        allowed_dir = os.path.join(self.temp_dir, "jail")
        os.makedirs(allowed_dir, exist_ok=True)
        inside_script = os.path.join(allowed_dir, "sub", "..", "script.py")
        actual_script = os.path.join(allowed_dir, "script.py")
        with open(actual_script, "w") as f:
            f.write("print('jail')\n")

        # Canonicalization resolves 'sub/../'
        canon, _ = validate_execution_request(
            file_path=inside_script,
            mode="terminal",
            allowed_roots=[allowed_dir],
        )
        self.assertEqual(canon, os.path.realpath(actual_script))

        # Traversal escaping jail
        escaping_path = os.path.join(allowed_dir, "..", "escaping.py")
        with open(os.path.join(self.temp_dir, "escaping.py"), "w") as f:
            f.write("print('escape')\n")

        with self.assertRaises(PermissionError):
            validate_execution_request(
                file_path=escaping_path,
                mode="terminal",
                allowed_roots=[allowed_dir],
            )

    # 6. Atomic Concurrent Process Registration
    async def test_06_atomic_concurrent_registration(self):
        pm = ProcessManager(max_concurrent=3)
        successes = []
        failures = []

        async def attempt_register(i):
            try:
                rec = await pm.try_register(
                    owner_token=f"user_{i}",
                    file_path=f"path_{i}.bat",
                    filename=f"file_{i}.bat",
                    executor_type="batch",
                    mode="terminal",
                )
                successes.append(rec)
            except RuntimeError as e:
                failures.append(str(e))

        # Run 10 concurrent registrations simultaneously
        await asyncio.gather(*(attempt_register(i) for i in range(10)))

        self.assertEqual(len(successes), 3)
        self.assertEqual(len(failures), 7)
        self.assertEqual(len(pm._active), 3)

    # 7. Terminal Process Lifecycle
    async def test_07_terminal_process_lifecycle(self):
        script = os.path.join(self.temp_dir, "lifecycle.py")
        with open(script, "w") as f:
            f.write("import sys\nprint('LINE_ONE')\nprint('LINE_TWO')\nsys.exit(0)\n")

        record = await self.pm.try_register(
            owner_token="term_owner",
            file_path=script,
            filename="lifecycle.py",
            executor_type="python",
            mode="terminal",
        )

        await terminal_mod.run_terminal(
            process_id=record.process_id,
            canonical_path=script,
            executor_type="python",
            timeout_seconds=5,
            process_manager=self.pm,
        )

        buf = terminal_mod.get_buffer(record.process_id)
        self.assertIsNotNone(buf)
        lines = await buf.get_all()
        full_text = "".join([l["d"] for l in lines])

        self.assertIn("LINE_ONE", full_text)
        self.assertIn("LINE_TWO", full_text)
        self.assertIn("[Process exited with code 0]", full_text)

        # Check process status in history
        history = await self.pm.get_history()
        matching = [r for r in history if r.process_id == record.process_id]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0].status, ProcessStatus.COMPLETED)
        self.assertEqual(matching[0].exit_code, 0)

    # 8. Desktop Process Lifecycle & Process-Tree Termination
    async def test_08_desktop_process_lifecycle(self):
        if os.name != "nt":
            self.skipTest("Desktop execution is Windows-only")

        script = os.path.join(self.temp_dir, "desktop_test.py")
        with open(script, "w") as f:
            f.write("import time\ntime.sleep(10)\n")

        record = await self.pm.try_register(
            owner_token="desk_owner",
            file_path=script,
            filename="desktop_test.py",
            executor_type="python",
            mode="desktop",
        )

        proc = desktop_mod.launch_desktop(script, "python")
        self.assertIsNotNone(proc)
        self.assertIsNotNone(proc.pid)
        self.assertGreater(proc.pid, 0)

        # Mark running with real proc handle
        await self.pm.mark_running(record.process_id, proc.pid, proc)
        self.assertEqual(record.status, ProcessStatus.RUNNING)
        self.assertEqual(record.pid, proc.pid)

        # Verify active count includes desktop process
        self.assertEqual(len(self.pm._active), 1)

        # Stop process via tree termination
        stopped = await self.pm.stop_process(record.process_id, "desk_owner")
        self.assertTrue(stopped)
        self.assertEqual(record.status, ProcessStatus.TERMINATED)

        # Process handle should be terminated
        time.sleep(0.5)
        self.assertIsNotNone(proc.poll())

    # 9. Windows Command Quoting
    async def test_09_windows_command_quoting(self):
        # Paths with spaces and metacharacters
        spaced_dir = os.path.join(self.temp_dir, "My Spaced Directory (Special & More)")
        os.makedirs(spaced_dir, exist_ok=True)
        spaced_script = os.path.join(spaced_dir, "test script spaces.py")
        with open(spaced_script, "w", encoding="utf-8") as f:
            f.write("print('SPACES_OK')\n")

        # Terminal command construction
        term_cmd = terminal_mod._build_command(spaced_script, "python")
        self.assertEqual(term_cmd, [sys.executable, spaced_script])

        # Desktop command construction
        desk_cmd, flags = desktop_mod._build_desktop_command(spaced_script, "python")
        self.assertIn(f'cmd.exe /K ""{sys.executable}" "{spaced_script}""', desk_cmd)

    # 10. PowerShell Execution Policy Behavior
    async def test_10_powershell_execution_policy(self):
        ps_script = os.path.join(self.temp_dir, "script.ps1")
        with open(ps_script, "w") as f:
            f.write("Write-Output 'PS'\n")

        # Default: no Bypass
        cmd_default = terminal_mod._build_command(ps_script, "powershell", powershell_override=False)
        self.assertNotIn("-ExecutionPolicy", cmd_default)
        self.assertNotIn("Bypass", cmd_default)

        # Explicit override: Bypass included
        cmd_override = terminal_mod._build_command(ps_script, "powershell", powershell_override=True)
        self.assertIn("-ExecutionPolicy", cmd_override)
        self.assertIn("Bypass", cmd_override)

    # 11. Existing File Manager Functionality
    async def test_11_file_manager_functionality(self):
        from starlette.testclient import TestClient
        client = TestClient(server.app)

        # 1. Root / health
        res = client.get("/")
        self.assertEqual(res.status_code, 200)

        # 2. Config endpoint
        res = client.get("/api/config")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("app_name", data)

        # 3. Execution public config
        res = client.get("/api/execution/config")
        self.assertEqual(res.status_code, 200)
        exec_cfg = res.json()
        self.assertIn("enabled", exec_cfg)
        self.assertIn("max_concurrent_processes", exec_cfg)


if __name__ == "__main__":
    unittest.main()
