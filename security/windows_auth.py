"""
security/windows_auth.py
------------------------
Client-side interface to the Windows-local authentication broker.

The server calls request_broker_auth() when an owner-management
operation requires local Windows authentication.

Communication:
  - Named pipe (local only): \\.\pipe\HydraAuthBroker
  - The broker process must be running (started by server.py on startup)
  - Uses the broker_protocol message format

Fallback:
  - If the broker is not running (pipe not found), returns a structured
    error. The caller must NOT fall back to PIN-only auth.
  - The server will report "Windows authentication unavailable" to the client.

Broker public key:
  - Loaded from broker.pub at startup and cached.
  - The server verifies every broker signature against this key.
  - If broker.pub changes (new broker instance), the cache is refreshed.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import time
from pathlib import Path
from typing import Optional, Tuple

from security.crypto import verify_signature, build_owner_op_message

logger = logging.getLogger(__name__)

_BASE_DIR = Path(__file__).resolve().parent.parent
_BROKER_PUB_PATH = _BASE_DIR / "broker.pub"
_PIPE_NAME = r"\\.\pipe\HydraAuthBroker"
_PIPE_TIMEOUT_MS = 5000    # Connection timeout
_AUTH_TIMEOUT_SECS = 150   # Auth dialog timeout (user has this long to respond)

# Cached broker public key (refreshed on each startup and on pub-file change)
_broker_pubkey_b64: Optional[str] = None
_broker_pubkey_mtime: float = 0.0


def _load_broker_pubkey() -> Optional[str]:
    """Load broker public key from broker.pub, return as base64url string."""
    global _broker_pubkey_b64, _broker_pubkey_mtime
    if not _BROKER_PUB_PATH.exists():
        return None
    try:
        mtime = _BROKER_PUB_PATH.stat().st_mtime
        if mtime != _broker_pubkey_mtime:
            raw = _BROKER_PUB_PATH.read_bytes()
            if len(raw) != 32:
                logger.error("broker.pub has unexpected length: %d", len(raw))
                return None
            _broker_pubkey_b64 = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
            _broker_pubkey_mtime = mtime
            logger.info("Loaded broker public key (fingerprint: %s...)", _broker_pubkey_b64[:8])
        return _broker_pubkey_b64
    except Exception as e:
        logger.error("Failed to load broker.pub: %s", e)
        return None


def is_broker_available() -> bool:
    """Return True if the broker.pub key file exists (broker has initialised)."""
    return _BROKER_PUB_PATH.exists()


# ---------------------------------------------------------------------------
# Named pipe communication (Windows only)
# ---------------------------------------------------------------------------

def _send_pipe_request_sync(action: str, challenge: str, display_msg: str) -> dict:
    """
    Synchronous named pipe call to the broker using native Windows kernel32 via ctypes.
    Zero external dependencies required (works on clean Python installations without pywin32).
    Returns the decoded response dict.
    Raises on connection failure, timeout, or pipe error.
    """
    if os.name != "nt":
        raise RuntimeError("Windows auth broker is only available on Windows")

    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32

    GENERIC_READ = 0x80000000
    GENERIC_WRITE = 0x40000000
    OPEN_EXISTING = 3
    INVALID_HANDLE_VALUE = -1

    request = json.dumps({
        "type": "auth_request",
        "action": action,
        "challenge": challenge,
        "display_msg": display_msg,
    }).encode("utf-8")

    handle = k32.CreateFileW(
        _PIPE_NAME,
        GENERIC_READ | GENERIC_WRITE,
        0, None,
        OPEN_EXISTING,
        0, None,
    )
    if handle == INVALID_HANDLE_VALUE or handle == 0xFFFFFFFFFFFFFFFF:
        err = k32.GetLastError()
        raise RuntimeError(f"Cannot connect to auth broker pipe (error {err}) — is the broker running?")

    try:
        written = wintypes.DWORD()
        if not k32.WriteFile(handle, request, len(request), ctypes.byref(written), None):
            err = k32.GetLastError()
            raise RuntimeError(f"Failed to write to broker pipe: error {err}")

        buf = ctypes.create_string_buffer(4096)
        read = wintypes.DWORD()
        if not k32.ReadFile(handle, buf, 4096, ctypes.byref(read), None):
            err = k32.GetLastError()
            raise RuntimeError(f"Failed to read from broker pipe: error {err}")

        data = buf.raw[:read.value]
        return json.loads(data.decode("utf-8").strip())
    finally:
        k32.CloseHandle(handle)


async def request_broker_auth(
    action: str,
    challenge: str,
    display_msg: str,
) -> Tuple[bool, Optional[str]]:
    """
    Request Windows authentication from the local broker (async).

    Returns:
        (success: bool, error_message: Optional[str])

    On success, the returned challenge response is verified against the
    broker public key INSIDE this function. Callers only see True/False.

    Args:
        action:      One of local_broker.broker_protocol.BrokerAction constants.
        challenge:   The server-generated challenge nonce (b64url).
        display_msg: Message shown in the Windows credential dialog.
    """
    pub_key = _load_broker_pubkey()
    if not pub_key:
        return False, "Windows auth broker public key not found — broker may not be running"

    loop = asyncio.get_event_loop()
    try:
        # Run sync pipe call in executor to avoid blocking the event loop
        response = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                _send_pipe_request_sync,
                action,
                challenge,
                display_msg,
            ),
            timeout=float(_AUTH_TIMEOUT_SECS),
        )
    except asyncio.TimeoutError:
        return False, "Windows authentication timed out"
    except RuntimeError as e:
        return False, str(e)
    except Exception as e:
        logger.error("Broker communication error: %s", type(e).__name__)
        return False, "Broker communication failed"

    if not response.get("success"):
        reason = response.get("error", "unknown")
        return False, f"Windows authentication denied: {reason}"

    # Critically verify the broker's signature against the known public key.
    # The message is (action + ":" + challenge) — matches broker.py _sign().
    sig = response.get("signature", "")
    broker_pubkey_from_response = response.get("broker_pubkey", "")

    # Ensure the response claims the same public key we know
    if broker_pubkey_from_response and broker_pubkey_from_response != pub_key:
        logger.error(
            "Broker returned unexpected public key! Expected %s..., got %s...",
            pub_key[:8], broker_pubkey_from_response[:8]
        )
        return False, "Broker public key mismatch — possible tampering"

    message = (action + ":" + challenge).encode("utf-8")
    if not verify_signature(pub_key, message, sig):
        logger.error("Broker signature verification FAILED for action=%s", action)
        return False, "Broker signature verification failed"

    logger.info("Broker auth verified OK for action=%s", action)
    return True, None
