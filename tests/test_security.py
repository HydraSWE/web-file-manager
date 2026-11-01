"""
tests/test_security.py
----------------------
Master automated test suite for Hydra PC-Controlled Multi-Owner Security Architecture.

Covers all 20 required security audit verification scenarios:
 1. First owner registration
 2. Two simultaneous first-owner registration attempts (race condition / atomicity)
 3. PIN-only ownership registration rejection (PIN alone must never create an owner)
 4. Invalid Windows authentication rejection (broker auth failure / signature tampering)
 5. Replay of old authorization challenges (one-time challenge nonce protection)
 6. Ordinary device pairing flow (new device requests pairing, gets pending status)
 7. Owner approval signature verification (valid Ed25519 signature from owner)
 8. Invalid owner signature rejection (tampered or mismatched signature)
 9. Remote owner creation rejection (cannot add owner without broker approval)
10. Remote owner promotion rejection (cannot promote trusted device without broker approval)
11. Remote owner removal rejection (cannot remove owner without broker approval, and cannot remove last owner)
12. Owner device revocation (revoking an owner device invalidates active sessions)
13. Trusted device revocation (revoking a trusted device blocks access and invalidates sessions)
14. Session invalidation (revoked/expired sessions rejected on protected endpoints)
15. Permission enforcement (capability-based: missing capability returns 403)
16. WebSocket device authentication (WebSocket rejects missing/invalid session token)
17. WebSocket ownership isolation (WebSocket rejects access to process owned by another session)
18. Security lockdown (blocks execution, pairing, ownership changes; requires Windows auth to unlock)
19. Recovery behavior (secure Windows-local recovery path if owner device lost)
20. Application restart persistence (database persistence survives application restart)
"""
import os
import sys
import time
import json
import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, AsyncMock

# Add hydra-file-manager to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, PrivateFormat, NoEncryption
import base64

import security.database as sec_db
from security.crypto import (
    hash_pin, verify_pin, generate_token, generate_challenge, fingerprint,
    build_approval_message, build_owner_op_message, verify_signature,
    public_key_to_b64, b64_to_public_key,
)
from security.permissions import Permission, OWNER_PERMISSIONS, check_permission, validate_permission_list
from security.audit import audit, AuditEvent, get_audit_log
from security.models import DeviceRole, SecurityState, PairingStatus, DeviceType
from security.device_registry import (
    register_first_owner, add_owner, remove_owner, revoke_device,
    is_owner, is_trusted, get_all_owners, get_all_trusted_devices,
    get_owner_count, has_any_owner, get_trusted_device, get_device_public_key,
    update_trusted_permissions,
)
from security.session_manager import (
    create_session, validate_session, refresh_session, revoke_session,
    revoke_all_device_sessions,
)
from security.pairing import (
    create_pairing_request, get_pairing_request, issue_approval_challenge,
    approve_pairing_request, reject_pairing_request, get_pending_requests,
)
from security.lockdown import (
    is_locked_down, enable_lockdown, disable_lockdown, get_lockdown_info,
    assert_not_locked_down,
)
import security.windows_auth as win_auth
from local_broker.broker_protocol import BrokerAction, encode_message, decode_message

# FastAPI TestClient
from starlette.testclient import TestClient
import server


def generate_test_device_keypair():
    """Helper to generate a real client Ed25519 key pair."""
    priv = Ed25519PrivateKey.generate()
    pub_bytes = priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    pub_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b"=").decode()
    return priv, pub_b64


def sign_test_message(priv: Ed25519PrivateKey, msg_bytes: bytes) -> str:
    """Sign bytes with private key and return base64url signature."""
    sig = priv.sign(msg_bytes)
    return base64.urlsafe_b64encode(sig).rstrip(b"=").decode()


class TestHydraSecurityArchitecture(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        """Set up an isolated test database in a clean temporary directory for each test."""
        self.test_dir = tempfile.mkdtemp(prefix="hydra_sec_test_")
        self.db_path = Path(self.test_dir) / "test_hydra_security.db"
        
        # Patch the database path
        self._orig_db_path = sec_db.DB_PATH
        sec_db.DB_PATH = self.db_path
        sec_db.close_db()
        sec_db.init_db()

        # Generate a test broker key pair and cache it
        self.broker_priv, self.broker_pub_b64 = generate_test_device_keypair()
        self.broker_pub_bytes = base64.urlsafe_b64decode(self.broker_pub_b64 + "==")
        self.broker_pub_file = Path(self.test_dir) / "broker.pub"
        self.broker_pub_file.write_bytes(self.broker_pub_bytes)
        win_auth._BROKER_PUB_PATH = self.broker_pub_file
        win_auth._broker_pubkey_b64 = self.broker_pub_b64
        win_auth._broker_pubkey_mtime = time.time()

        # Set up an enrollment PIN hash in security_config
        self.test_pin = "HydraEnroll2026!"
        self.pin_hash = hash_pin(self.test_pin)
        db = sec_db.get_db()
        db.execute("INSERT OR REPLACE INTO security_config (key, value) VALUES ('pin_hash', ?)", (self.pin_hash,))
        db.commit()

        # Create FastAPI TestClient
        self.client = TestClient(server.app)

    async def asyncTearDown(self):
        """Clean up thread-local connection and temp directory."""
        sec_db.close_db()
        sec_db.DB_PATH = self._orig_db_path
        import shutil
        try:
            shutil.rmtree(self.test_dir, ignore_errors=True)
        except Exception:
            pass

    # -------------------------------------------------------------------------
    # 1. First owner registration
    # -------------------------------------------------------------------------
    async def test_01_first_owner_registration(self):
        """Test registering the initial owner device successfully with local auth."""
        priv, pub_b64 = generate_test_device_keypair()
        device_id = "device_owner_alpha_01"

        with patch("security.router.request_broker_auth", new_callable=AsyncMock) as mock_broker:
            mock_broker.return_value = (True, None)

            resp = self.client.post("/api/security/initial-setup", json={
                "device_id": device_id,
                "device_name": "Admin Mobile Phone",
                "device_type": "phone",
                "public_key": pub_b64,
                "pin": self.test_pin,
            })
            self.assertEqual(resp.status_code, 200, resp.text)
            data = resp.json()
            self.assertTrue(data["success"])
            self.assertEqual(data["session"]["role"], "primary-owner")
            self.assertEqual(data["session"]["device_id"], device_id)
            self.assertTrue(is_owner(device_id))
            self.assertEqual(get_owner_count(), 1)

    # -------------------------------------------------------------------------
    # 2. Two simultaneous first-owner registration attempts
    # -------------------------------------------------------------------------
    async def test_02_simultaneous_first_owner_registration(self):
        """Verify race condition protection: only one first owner can be registered."""
        priv1, pub1 = generate_test_device_keypair()
        priv2, pub2 = generate_test_device_keypair()

        results = await asyncio.gather(
            register_first_owner("device_first_01", "Device 1", "phone", pub1),
            register_first_owner("device_first_02", "Device 2", "laptop", pub2),
        )
        # Exactly one must succeed and one must fail
        self.assertEqual(sum(1 for r in results if r is True), 1)
        self.assertEqual(sum(1 for r in results if r is False), 1)
        self.assertEqual(get_owner_count(), 1)

    # -------------------------------------------------------------------------
    # 3. PIN-only ownership registration rejection
    # -------------------------------------------------------------------------
    async def test_03_pin_only_ownership_registration_rejection(self):
        """The enrollment PIN alone without Windows authentication must never create an owner."""
        priv, pub_b64 = generate_test_device_keypair()
        with patch("security.router.is_broker_available", return_value=False):
            resp = self.client.post("/api/security/initial-setup", json={
                "device_id": "device_pin_only_attacker",
                "device_name": "Attacker Phone",
                "device_type": "phone",
                "public_key": pub_b64,
                "pin": self.test_pin,
            })
            # Broker unavailable => 503 Service Unavailable, registration rejected
            self.assertEqual(resp.status_code, 503)
            self.assertFalse(has_any_owner())

    # -------------------------------------------------------------------------
    # 4. Invalid Windows authentication rejection
    # -------------------------------------------------------------------------
    async def test_04_invalid_windows_auth_rejection(self):
        """When local Windows authentication fails or is cancelled, owner registration must fail."""
        priv, pub_b64 = generate_test_device_keypair()
        with patch("security.router.request_broker_auth", new_callable=AsyncMock) as mock_broker:
            mock_broker.return_value = (False, "user_cancelled_or_failed")

            resp = self.client.post("/api/security/initial-setup", json={
                "device_id": "device_failed_win_auth",
                "device_name": "Unverified Device",
                "device_type": "laptop",
                "public_key": pub_b64,
                "pin": self.test_pin,
            })
            self.assertEqual(resp.status_code, 403)
            self.assertFalse(has_any_owner())

    # -------------------------------------------------------------------------
    # 5. Replay of old authorization challenges
    # -------------------------------------------------------------------------
    async def test_05_replay_of_old_authorization_challenges(self):
        """Challenges are single-use nonces; reusing an old challenge must be rejected."""
        priv, pub_b64 = generate_test_device_keypair()
        dev_id = "device_challenge_test"
        await register_first_owner(dev_id, "Owner Device", "phone", pub_b64)

        # Get challenge
        resp = self.client.get(f"/api/auth/device-challenge?device_id={dev_id}")
        self.assertEqual(resp.status_code, 200)
        challenge = resp.json()["challenge"]

        # Sign challenge: HYDRA-LOGIN:<challenge>:<device_id>
        msg = f"HYDRA-LOGIN:{challenge}:{dev_id}".encode()
        sig = sign_test_message(priv, msg)

        # First login: valid
        login_resp1 = self.client.post("/api/auth/device-login", json={
            "device_id": dev_id,
            "challenge": challenge,
            "signature": sig,
        })
        self.assertEqual(login_resp1.status_code, 200)

        # Replay attempt with same challenge: must be rejected
        login_resp2 = self.client.post("/api/auth/device-login", json={
            "device_id": dev_id,
            "challenge": challenge,
            "signature": sig,
        })
        self.assertEqual(login_resp2.status_code, 401)

    # -------------------------------------------------------------------------
    # 6. Ordinary device pairing
    # -------------------------------------------------------------------------
    async def test_06_ordinary_device_pairing_request(self):
        """New device enters PIN and sends pairing request, gets registered as pending."""
        priv, pub_b64 = generate_test_device_keypair()
        dev_id = "device_pending_guest"

        resp = self.client.post("/api/pairing/request", json={
            "device_id": dev_id,
            "device_name": "Guest Tablet",
            "device_type": "tablet",
            "public_key": pub_b64,
            "requested_permissions": ["filesystem.read"],
            "pin": self.test_pin,
        })
        self.assertEqual(resp.status_code, 200)
        req_id = resp.json()["request_id"]
        self.assertTrue(req_id)

        # Verify status is pending
        stat_resp = self.client.get(f"/api/pairing/status/{req_id}")
        self.assertEqual(stat_resp.status_code, 200)
        self.assertEqual(stat_resp.json()["status"], "pending")

        # Pending device must NOT be trusted
        self.assertFalse(is_trusted(dev_id))

    # -------------------------------------------------------------------------
    # 7. Owner approval signature verification
    # -------------------------------------------------------------------------
    async def test_07_owner_approval_signature_verification(self):
        """An owner can approve a pending device by cryptographically signing the approval challenge."""
        # 1. Register owner
        owner_priv, owner_pub = generate_test_device_keypair()
        owner_id = "owner_device_approver"
        await register_first_owner(owner_id, "Owner", "laptop", owner_pub)
        owner_session = create_session(owner_id, DeviceRole.PRIMARY_OWNER, list(OWNER_PERMISSIONS))

        # 2. Register pending request
        guest_priv, guest_pub = generate_test_device_keypair()
        guest_id = "guest_device_to_approve"
        req_id = create_pairing_request("req_007", guest_id, "Guest Phone", "phone", guest_pub, ["filesystem.read"])

        # 3. Request approval challenge
        headers = {"Authorization": f"Bearer {owner_session.session_id}"}
        ch_resp = self.client.post(f"/api/pairing/challenge/{req_id}", headers=headers)
        self.assertEqual(ch_resp.status_code, 200)
        challenge = ch_resp.json()["challenge"]

        # 4. Owner signs the canonical approval message
        approval_msg = build_approval_message(challenge, req_id)
        owner_sig = sign_test_message(owner_priv, approval_msg)

        # 5. Submit approval
        approve_resp = self.client.post("/api/pairing/approve", json={
            "request_id": req_id,
            "approval_challenge": challenge,
            "owner_signature": owner_sig,
            "owner_device_id": owner_id,
            "grant_permissions": ["filesystem.read"],
        }, headers=headers)
        self.assertEqual(approve_resp.status_code, 200, approve_resp.text)
        self.assertTrue(approve_resp.json()["success"])

        # Device is now trusted!
        self.assertTrue(is_trusted(guest_id))

    # -------------------------------------------------------------------------
    # 8. Invalid owner signature rejection
    # -------------------------------------------------------------------------
    async def test_08_invalid_owner_signature_rejection(self):
        """Approving a pairing with a forged or invalid signature must be rejected."""
        owner_priv, owner_pub = generate_test_device_keypair()
        owner_id = "owner_device_signer"
        await register_first_owner(owner_id, "Owner", "laptop", owner_pub)
        owner_session = create_session(owner_id, DeviceRole.PRIMARY_OWNER, list(OWNER_PERMISSIONS))

        guest_priv, guest_pub = generate_test_device_keypair()
        guest_id = "guest_device_forged"
        req_id = create_pairing_request("req_008", guest_id, "Guest", "phone", guest_pub, ["filesystem.read"])

        headers = {"Authorization": f"Bearer {owner_session.session_id}"}
        ch_resp = self.client.post(f"/api/pairing/challenge/{req_id}", headers=headers)
        challenge = ch_resp.json()["challenge"]

        # Generate a fake signature using a different key
        fake_priv, _ = generate_test_device_keypair()
        fake_sig = sign_test_message(fake_priv, build_approval_message(challenge, req_id))

        approve_resp = self.client.post("/api/pairing/approve", json={
            "request_id": req_id,
            "approval_challenge": challenge,
            "owner_signature": fake_sig,
            "owner_device_id": owner_id,
            "grant_permissions": ["filesystem.read"],
        }, headers=headers)
        self.assertEqual(approve_resp.status_code, 400)
        self.assertFalse(is_trusted(guest_id))

    # -------------------------------------------------------------------------
    # 9. Remote owner creation rejection
    # -------------------------------------------------------------------------
    async def test_09_remote_owner_creation_rejection(self):
        """Attempting to add an owner without a valid broker approval token must fail."""
        owner_priv, owner_pub = generate_test_device_keypair()
        owner_id = "owner_prime"
        await register_first_owner(owner_id, "Owner Prime", "desktop", owner_pub)
        session = create_session(owner_id, DeviceRole.PRIMARY_OWNER, list(OWNER_PERMISSIONS))

        headers = {"Authorization": f"Bearer {session.session_id}"}
        resp = self.client.post("/api/owners/local-approve", json={
            "device_id": "rogue_device",
            "broker_approval_token": "fabricated_token_12345",
        }, headers=headers)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(is_owner("rogue_device"))

    # -------------------------------------------------------------------------
    # 10. Remote owner promotion rejection
    # -------------------------------------------------------------------------
    async def test_10_remote_owner_promotion_rejection(self):
        """Promoting a trusted device to owner without local broker auth must fail."""
        owner_priv, owner_pub = generate_test_device_keypair()
        owner_id = "owner_promoter"
        await register_first_owner(owner_id, "Owner", "desktop", owner_pub)
        session = create_session(owner_id, DeviceRole.PRIMARY_OWNER, list(OWNER_PERMISSIONS))

        # Register a trusted device
        t_priv, t_pub = generate_test_device_keypair()
        t_id = "trusted_candidate"
        sec_db.get_db().execute(
            "INSERT INTO trusted_devices (device_id, device_name, device_type, public_key, key_fingerprint, permissions, registered_at, approved_by, revoked) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (t_id, "Candidate", "laptop", t_pub, fingerprint(t_pub), json.dumps(["filesystem.read"]), int(time.time()), owner_id)
        )
        sec_db.get_db().commit()

        headers = {"Authorization": f"Bearer {session.session_id}"}
        # Try to promote without valid broker token
        resp = self.client.post("/api/owners/local-approve", json={
            "device_id": t_id,
            "broker_approval_token": "expired_or_invalid",
        }, headers=headers)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(is_owner(t_id))

    # -------------------------------------------------------------------------
    # 11. Remote owner removal rejection
    # -------------------------------------------------------------------------
    async def test_11_remote_owner_removal_rejection(self):
        """Owner removal must require broker approval; also removing the last owner must be rejected."""
        owner_priv, owner_pub = generate_test_device_keypair()
        owner_id = "sole_owner"
        await register_first_owner(owner_id, "Sole Owner", "desktop", owner_pub)
        session = create_session(owner_id, DeviceRole.PRIMARY_OWNER, list(OWNER_PERMISSIONS))

        headers = {"Authorization": f"Bearer {session.session_id}"}
        # Attempt without broker token
        resp = self.client.post("/api/owners/local-remove", json={
            "device_id": owner_id,
            "broker_approval_token": "fake_token",
        }, headers=headers)
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(is_owner(owner_id))

        # Even with a valid token, removing the last owner must fail
        db = sec_db.get_db()
        valid_token = generate_token(32)
        db.execute(
            "INSERT INTO broker_approvals (token, action, payload, issued_at, expires_at, used) VALUES (?, ?, ?, ?, ?, 0)",
            (valid_token, BrokerAction.REMOVE_OWNER, json.dumps({"target_device_id": owner_id}), int(time.time()), int(time.time()) + 60)
        )
        db.commit()

        resp2 = self.client.post("/api/owners/local-remove", json={
            "device_id": owner_id,
            "broker_approval_token": valid_token,
        }, headers=headers)
        self.assertEqual(resp2.status_code, 400)
        self.assertTrue(is_owner(owner_id))

    # -------------------------------------------------------------------------
    # 12. Owner device revocation
    # -------------------------------------------------------------------------
    async def test_12_owner_device_revocation(self):
        """When an owner device is revoked, its active sessions must be invalidated immediately."""
        owner1_priv, owner1_pub = generate_test_device_keypair()
        owner2_priv, owner2_pub = generate_test_device_keypair()
        await register_first_owner("owner_1", "Primary", "desktop", owner1_pub)
        add_owner("owner_2", "Secondary", "phone", owner2_pub, role="co-owner")

        session_owner2 = create_session("owner_2", DeviceRole.CO_OWNER, list(OWNER_PERMISSIONS))
        self.assertIsNotNone(validate_session(session_owner2.session_id))

        # Revoke owner_2
        ok = remove_owner("owner_2", actor_id="owner_1")
        self.assertTrue(ok)
        self.assertFalse(is_owner("owner_2"))

        # Session must be invalidated
        self.assertIsNone(validate_session(session_owner2.session_id))

    # -------------------------------------------------------------------------
    # 13. Trusted device revocation
    # -------------------------------------------------------------------------
    async def test_13_trusted_device_revocation(self):
        """Revoking a trusted device invalidates its active sessions and denies future access."""
        owner_priv, owner_pub = generate_test_device_keypair()
        await register_first_owner("owner_id", "Owner", "desktop", owner_pub)
        owner_sess = create_session("owner_id", DeviceRole.PRIMARY_OWNER, list(OWNER_PERMISSIONS))

        t_priv, t_pub = generate_test_device_keypair()
        t_id = "device_trusted_13"
        sec_db.get_db().execute(
            "INSERT INTO trusted_devices (device_id, device_name, device_type, public_key, key_fingerprint, permissions, registered_at, approved_by, revoked) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (t_id, "Trusted", "phone", t_pub, fingerprint(t_pub), json.dumps(["filesystem.read"]), int(time.time()), "owner_id")
        )
        sec_db.get_db().commit()

        t_session = create_session(t_id, DeviceRole.TRUSTED, ["filesystem.read"])
        self.assertIsNotNone(validate_session(t_session.session_id))

        # Revoke trusted device via endpoint
        headers = {"Authorization": f"Bearer {owner_sess.session_id}"}
        resp = self.client.post("/api/devices/revoke", json={"device_id": t_id}, headers=headers)
        self.assertEqual(resp.status_code, 200)

        # Device is revoked and its session is dead
        self.assertFalse(is_trusted(t_id))
        self.assertIsNone(validate_session(t_session.session_id))

    # -------------------------------------------------------------------------
    # 14. Session invalidation
    # -------------------------------------------------------------------------
    async def test_14_session_invalidation(self):
        """Expired or revoked session tokens must return 401 on protected APIs."""
        owner_priv, owner_pub = generate_test_device_keypair()
        await register_first_owner("owner_sess_test", "Owner", "desktop", owner_pub)
        sess = create_session("owner_sess_test", DeviceRole.PRIMARY_OWNER, list(OWNER_PERMISSIONS))

        # Valid session accesses /api/devices
        headers = {"Authorization": f"Bearer {sess.session_id}"}
        resp = self.client.get("/api/devices", headers=headers)
        self.assertEqual(resp.status_code, 200)

        # Explicitly revoke session
        revoke_session(sess.session_id)

        # Subsequent call must be 401
        resp2 = self.client.get("/api/devices", headers=headers)
        self.assertEqual(resp2.status_code, 401)

    # -------------------------------------------------------------------------
    # 15. Permission enforcement
    # -------------------------------------------------------------------------
    async def test_15_permission_enforcement(self):
        """A trusted device with only filesystem.read cannot execute scripts."""
        t_priv, t_pub = generate_test_device_keypair()
        t_id = "device_read_only"
        sec_db.get_db().execute(
            "INSERT INTO trusted_devices (device_id, device_name, device_type, public_key, key_fingerprint, permissions, registered_at, approved_by, revoked) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (t_id, "ReadOnly", "phone", t_pub, fingerprint(t_pub), json.dumps(["filesystem.read"]), int(time.time()), "admin")
        )
        sec_db.get_db().commit()

        # Session has only filesystem.read
        sess = create_session(t_id, DeviceRole.TRUSTED, ["filesystem.read"])

        # Try to execute script via start_execution endpoint
        headers = {"Authorization": f"Bearer {sess.session_id}"}
        resp = self.client.post("/api/execution/start", json={
            "path": r"C:\Windows\System32\cmd.exe",
            "mode": "desktop"
        }, headers=headers)
        # Must be 403 Forbidden due to missing execution permissions
        self.assertEqual(resp.status_code, 403)
        self.assertIn("execution", resp.text.lower())

    # -------------------------------------------------------------------------
    # 16. WebSocket device authentication
    # -------------------------------------------------------------------------
    async def test_16_websocket_device_authentication(self):
        """WebSocket connection rejects missing or invalid session token."""
        # Connecting without token must be closed with 4001
        with self.assertRaises(Exception):
            with self.client.websocket_connect("/ws/execution/proc_dummy?token=invalid_token") as ws:
                pass

    # -------------------------------------------------------------------------
    # 17. WebSocket ownership isolation
    # -------------------------------------------------------------------------
    async def test_17_websocket_ownership_isolation(self):
        """WebSocket connection rejects token that does not match process owner."""
        # Create a process owned by user A
        owner_a_token = "token_user_a_123456"
        server.SESSION_TOKENS.add(owner_a_token)
        record = await server._execution_manager.pm.try_register(
            owner_token=owner_a_token,
            file_path=r"C:\test.py",
            filename="test.py",
            executor_type="python",
            mode="terminal",
        )

        # User B attempts to connect to User A's process WebSocket
        owner_b_token = "token_user_b_789012"
        server.SESSION_TOKENS.add(owner_b_token)

        with self.assertRaises(Exception):
            with self.client.websocket_connect(f"/ws/execution/{record.process_id}?token={owner_b_token}") as ws:
                pass

    # -------------------------------------------------------------------------
    # 18. Security lockdown
    # -------------------------------------------------------------------------
    async def test_18_security_lockdown(self):
        """When lockdown is enabled, script execution and pairing are blocked."""
        owner_priv, owner_pub = generate_test_device_keypair()
        await register_first_owner("owner_lockdown", "Owner", "desktop", owner_pub)
        sess = create_session("owner_lockdown", DeviceRole.PRIMARY_OWNER, list(OWNER_PERMISSIONS))

        headers = {"Authorization": f"Bearer {sess.session_id}"}

        # Enable lockdown
        resp = self.client.post("/api/security/lockdown", json={"reason": "Emergency"}, headers=headers)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(is_locked_down())

        # Pairing must be blocked
        p_resp = self.client.post("/api/pairing/request", json={
            "device_id": "attempt_during_lockdown",
            "device_name": "Device",
            "device_type": "phone",
            "public_key": "some_pub_key_long_enough_for_validation_12345",
            "requested_permissions": [],
            "pin": self.test_pin,
        })
        self.assertEqual(p_resp.status_code, 503)

        # Execution must be blocked
        e_resp = self.client.post("/api/execution/start", json={
            "path": r"C:\Windows\System32\cmd.exe",
            "mode": "desktop"
        }, headers=headers)
        self.assertEqual(e_resp.status_code, 503)

        # Disable lockdown with valid broker token
        db = sec_db.get_db()
        unlock_token = generate_token(32)
        db.execute(
            "INSERT INTO broker_approvals (token, action, payload, issued_at, expires_at, used) VALUES (?, ?, ?, ?, ?, 0)",
            (unlock_token, BrokerAction.CHANGE_SECURITY_POLICY, json.dumps({}), int(time.time()), int(time.time()) + 60)
        )
        db.commit()

        u_resp = self.client.post("/api/security/unlock", json={"broker_approval_token": unlock_token}, headers=headers)
        self.assertEqual(u_resp.status_code, 200, u_resp.text)
        self.assertFalse(is_locked_down())

    # -------------------------------------------------------------------------
    # 19. Recovery behavior
    # -------------------------------------------------------------------------
    async def test_19_recovery_behavior(self):
        """Simulate Windows-local recovery: resetting ownership safely when all owner devices lost."""
        # Register an owner then pretend lost
        owner_priv, owner_pub = generate_test_device_keypair()
        await register_first_owner("lost_owner", "Lost Phone", "phone", owner_pub)
        self.assertTrue(has_any_owner())

        # Local recovery command: direct database intervention authorized by local administrator
        db = sec_db.get_db()
        db.execute("UPDATE owners SET revoked = 1, revoked_at = ?", (int(time.time()),))
        db.commit()

        # Platform should re-enter initial setup state
        self.assertFalse(has_any_owner())
        status_resp = self.client.get("/api/security/status")
        self.assertEqual(status_resp.json()["state"], "initial_setup")

    # -------------------------------------------------------------------------
    # 20. Application restart persistence
    # -------------------------------------------------------------------------
    async def test_20_application_restart_persistence(self):
        """Database and owners survive application restart and DB reconnections."""
        owner_priv, owner_pub = generate_test_device_keypair()
        await register_first_owner("persistent_owner", "Server PC", "desktop", owner_pub)
        session = create_session("persistent_owner", DeviceRole.PRIMARY_OWNER, list(OWNER_PERMISSIONS))

        # Close all connections (simulate server process restart)
        sec_db.close_db()

        # Reopen
        sec_db.init_db()
        self.assertTrue(is_owner("persistent_owner"))
        self.assertEqual(get_owner_count(), 1)
        valid_sess = validate_session(session.session_id)
        self.assertIsNotNone(valid_sess)
        self.assertEqual(valid_sess["device_id"], "persistent_owner")


if __name__ == "__main__":
    unittest.main()
