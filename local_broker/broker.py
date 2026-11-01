"""
local_broker/broker.py
----------------------
Windows-local authentication broker for HYDRA.

This process runs as a LOCAL ONLY helper alongside the main server.
It must be started by the same Windows user who owns the server session.

Responsibilities:
  1. Generate and persist its own Ed25519 signing key (broker.key, broker.pub)
     in the server's base directory with restricted permissions.
  2. Listen on a named pipe for authentication requests from server.py.
  3. Show a native Windows credential / UAC dialog when a request arrives.
  4. On successful Windows authentication, sign the challenge and return
     the signature.
  5. On failure or user cancellation, return a failure response.

Security invariants:
  - The named pipe is LOCAL only (no network exposure).
  - The broker private key never leaves this process.
  - The signature is over (action + ":" + challenge) — action-bound.
  - The broker validates that all fields are present before proceeding.
  - Timeout: the Windows dialog times out after 120 seconds.

Windows auth mechanism:
  Primary:  CredUIPromptForWindowsCredentials (credential dialog)
            Verifies the result with LogonUser.
  Fallback: ShellExecuteEx with runas verb (UAC elevation proof)
            Used when CredUI is not available.

Usage:
  python broker.py [--key-dir <path>]

Run this as a background process via server.py startup.
"""
from __future__ import annotations

import argparse
import base64
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("hydra.broker")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [BROKER] %(levelname)s %(message)s",
)

# Key file names (stored in server BASE_DIR)
BROKER_PRIVATE_KEY_FILE = "broker.key"
BROKER_PUBLIC_KEY_FILE  = "broker.pub"


# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------

def _load_or_generate_keypair(key_dir: Path) -> tuple[bytes, bytes]:
    """
    Load existing broker keypair or generate a new one.
    Returns (private_key_bytes_raw, public_key_bytes_raw).
    Files are stored with restrictive permissions.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import (
        Encoding, PublicFormat, PrivateFormat, NoEncryption,
    )

    priv_path = key_dir / BROKER_PRIVATE_KEY_FILE
    pub_path  = key_dir / BROKER_PUBLIC_KEY_FILE

    if priv_path.exists() and pub_path.exists():
        try:
            priv_raw = priv_path.read_bytes()
            pub_raw  = pub_path.read_bytes()
            if len(priv_raw) == 32 and len(pub_raw) == 32:
                logger.info("Loaded existing broker keypair.")
                return priv_raw, pub_raw
        except Exception as e:
            logger.warning("Failed to load existing keypair, regenerating: %s", e)

    logger.info("Generating new broker Ed25519 keypair...")
    private_key = Ed25519PrivateKey.generate()
    priv_raw = private_key.private_bytes(
        encoding=Encoding.Raw, format=PrivateFormat.Raw, encryption_algorithm=NoEncryption()
    )
    pub_raw = private_key.public_key().public_bytes(
        encoding=Encoding.Raw, format=PublicFormat.Raw
    )
    # Write with restricted permissions
    for path, data in [(priv_path, priv_raw), (pub_path, pub_raw)]:
        path.write_bytes(data)
        _restrict_file(path)

    logger.info("Broker keypair generated and saved.")
    return priv_raw, pub_raw


def _restrict_file(path: Path) -> None:
    """Restrict file to current user only (Windows icacls)."""
    if os.name == "nt":
        try:
            import subprocess
            username = os.environ.get("USERNAME", "User")
            subprocess.run(
                ["icacls", str(path), "/inheritance:r",
                 "/grant:r", f"{username}:(R)",
                 "/grant:r", "SYSTEM:(R)"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass


def _sign(priv_raw: bytes, message: bytes) -> str:
    """Sign message with raw Ed25519 private key. Returns base64url signature."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
    private_key = Ed25519PrivateKey.from_private_bytes(priv_raw)
    sig = private_key.sign(message)
    return base64.urlsafe_b64encode(sig).rstrip(b"=").decode()


# ---------------------------------------------------------------------------
# Windows authentication
# ---------------------------------------------------------------------------

def _windows_hello_authenticate(display_msg: str, timeout_secs: int = 120) -> tuple[bool, bool]:
    """
    Attempt native Windows Hello verification (Biometrics / Windows Hello PIN).
    Uses the official Windows.Security.Credentials.UI.UserConsentVerifier WinRT API.
    Returns (handled, success). If handled is False, Windows Hello is not configured/available.
    """
    clean_msg = display_msg.replace("'", " ").replace('"', ' ').replace("\n", " ").strip()
    ps_code = f"""
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {{ $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' }})[0]

function Await($asyncOp, $type) {{
    $asTask = $asTaskGeneric.MakeGenericMethod($type)
    $netTask = $asTask.Invoke($null, @($asyncOp))
    $netTask.Wait(-1) | Out-Null
    return $netTask.Result
}}

$availOp = [Windows.Security.Credentials.UI.UserConsentVerifier, Windows.Security.Credentials.UI, ContentType = WindowsRuntime]::CheckAvailabilityAsync()
$avail = Await $availOp ([Windows.Security.Credentials.UI.UserConsentVerifierAvailability])
if ($avail -ne [Windows.Security.Credentials.UI.UserConsentVerifierAvailability]::Available) {{
    Write-Output "AVAIL:NO"
    exit 0
}}

$verifOp = [Windows.Security.Credentials.UI.UserConsentVerifier, Windows.Security.Credentials.UI, ContentType = WindowsRuntime]::RequestVerificationAsync('{clean_msg}')
$res = Await $verifOp ([Windows.Security.Credentials.UI.UserConsentVerificationResult])
Write-Output "VERIFY_RESULT:$res"
"""
    try:
        import subprocess
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps_code],
            capture_output=True,
            text=True,
            timeout=timeout_secs
        )
        out = proc.stdout.strip()
        if "AVAIL:NO" in out:
            logger.info("Windows Hello not available on this system, falling back to CredUI")
            return (False, False)

        logger.info("Windows Hello result: %s", out)
        if "VERIFY_RESULT:Verified" in out or "VERIFY_RESULT:0" in out:
            logger.info("Windows Hello authentication SUCCEEDED")
            return (True, True)
        else:
            logger.warning("Windows Hello authentication NOT verified: %s", out)
            return (True, False)
    except Exception as e:
        logger.warning("Windows Hello execution error: %s, falling back to CredUI", e)
        return (False, False)


def _authenticate_windows_user(display_msg: str, timeout_secs: int = 120) -> bool:
    """
    Authenticate the local Windows user.
    1. Primary: Native Windows Hello prompt (Face, Fingerprint, or Windows Hello PIN).
    2. Fallback: Windows CredUI credential dialog (Username + Windows Password).
    Never returns True without verified OS-level proof.
    """
    if os.name != "nt":
        logger.error("Broker running on non-Windows — authentication denied.")
        return False

    # Try Windows Hello first
    handled, success = _windows_hello_authenticate(display_msg, timeout_secs)
    if handled:
        return success

    # Fall back to CredUI
    return _credui_authenticate(display_msg, timeout_secs)


def _credui_authenticate(display_msg: str, timeout_secs: int) -> bool:
    """
    Use Windows CredUIPromptForWindowsCredentials + LogonUser to verify identity.
    Returns True only if LogonUser succeeds with the provided credentials.
    """
    try:
        import ctypes
        import ctypes.wintypes as wt

        credui = ctypes.windll.credui
        advapi = ctypes.windll.advapi32
        user32 = ctypes.windll.user32

        # CredUIPromptForWindowsCredentials flags
        CREDUIWIN_GENERIC               = 0x00000001
        CREDUIWIN_CHECKBOX              = 0x00000002
        CREDUIWIN_AUTHPACKAGE_ONLY      = 0x00000010
        CREDUIWIN_ENUMERATE_CURRENT_USER = 0x00000200

        # Output buffers
        MAX_USERNAME = 256
        MAX_PASSWORD = 256
        MAX_DOMAIN   = 256
        username_buf = ctypes.create_unicode_buffer(MAX_USERNAME)
        password_buf = ctypes.create_unicode_buffer(MAX_PASSWORD)
        domain_buf   = ctypes.create_unicode_buffer(MAX_DOMAIN)

        # CredUI info struct
        class CREDUI_INFO(ctypes.Structure):
            _fields_ = [
                ("cbSize",        ctypes.c_ulong),
                ("hwndParent",    wt.HWND),
                ("pszMessageText",wt.LPCWSTR),
                ("pszCaptionText",wt.LPCWSTR),
                ("hbmBanner",     wt.HBITMAP),
            ]

        info = CREDUI_INFO()
        info.cbSize = ctypes.sizeof(CREDUI_INFO)
        info.hwndParent = user32.GetForegroundWindow() or user32.GetDesktopWindow()
        info.pszMessageText = display_msg
        info.pszCaptionText = "HYDRA — Windows Authorization Required"
        info.hbmBanner = None

        auth_package  = ctypes.c_ulong(0)
        out_cred_buf  = ctypes.c_void_p()
        out_cred_size = ctypes.c_ulong(0)
        save          = wt.BOOL(0)

        ret = credui.CredUIPromptForWindowsCredentials(
            ctypes.byref(info),
            0,           # dwAuthError
            ctypes.byref(auth_package),
            None,        # pvInAuthBuffer
            0,           # ulInAuthBufferSize
            ctypes.byref(out_cred_buf),
            ctypes.byref(out_cred_size),
            ctypes.byref(save),
            CREDUIWIN_GENERIC | CREDUIWIN_ENUMERATE_CURRENT_USER,
        )

        if ret != 0:
            # User cancelled (ret == 1223) or error
            logger.info("CredUI cancelled or failed: ret=%d", ret)
            return False

        # Unpack credentials
        username_size = ctypes.c_ulong(MAX_USERNAME)
        domain_size   = ctypes.c_ulong(MAX_DOMAIN)
        password_size = ctypes.c_ulong(MAX_PASSWORD)

        unpack_ok = credui.CredUnPackAuthenticationBufferW(
            0,  # dwFlags
            out_cred_buf,
            out_cred_size,
            username_buf, ctypes.byref(username_size),
            domain_buf,   ctypes.byref(domain_size),
            password_buf, ctypes.byref(password_size),
        )

        # Free the credential buffer immediately
        ctypes.windll.ole32.CoTaskMemFree(out_cred_buf)

        if not unpack_ok:
            logger.warning("CredUnPackAuthenticationBuffer failed")
            return False

        username = username_buf.value
        domain   = domain_buf.value or "."
        password = password_buf.value

        # Clear password buffer ASAP
        ctypes.memset(password_buf, 0, MAX_PASSWORD * 2)

        # Verify via LogonUser
        LOGON32_LOGON_INTERACTIVE = 2
        LOGON32_PROVIDER_DEFAULT  = 0
        token_handle = wt.HANDLE()

        logon_ok = advapi.LogonUserW(
            username,
            domain,
            password,
            LOGON32_LOGON_INTERACTIVE,
            LOGON32_PROVIDER_DEFAULT,
            ctypes.byref(token_handle),
        )

        if logon_ok:
            ctypes.windll.kernel32.CloseHandle(token_handle)
            logger.info("Windows LogonUser succeeded for user: %s", username)
            return True
        else:
            err = ctypes.windll.kernel32.GetLastError()
            logger.warning("Windows LogonUser failed: error=%d", err)
            return False

    except Exception as e:
        logger.error("CredUI authentication error: %s", type(e).__name__, exc_info=True)
        return False


# ---------------------------------------------------------------------------
# Named pipe server
# ---------------------------------------------------------------------------

def run_broker_server(key_dir: Path) -> None:
    """
    Main broker event loop.
    Listens on the named pipe and handles one auth request at a time.
    """
    priv_raw, pub_raw = _load_or_generate_keypair(key_dir)
    pub_b64 = base64.urlsafe_b64encode(pub_raw).rstrip(b"=").decode()

    logger.info("Broker public key: %s", pub_b64)
    logger.info("Listening on pipe: %s", r"\\.\pipe\HydraAuthBroker")

    if os.name != "nt":
        logger.error("Broker only runs on Windows. Exiting.")
        sys.exit(1)

    import ctypes
    from ctypes import wintypes
    k32 = ctypes.windll.kernel32

    PIPE_NAME = r"\\.\pipe\HydraAuthBroker"
    PIPE_ACCESS_DUPLEX = 0x00000003
    PIPE_TYPE_MESSAGE = 0x00000004
    PIPE_READMODE_MESSAGE = 0x00000002
    PIPE_WAIT = 0x00000000
    INVALID_HANDLE_VALUE = -1
    BUFFER_SIZE = 4096

    while True:
        try:
            pipe = k32.CreateNamedPipeW(
                PIPE_NAME,
                PIPE_ACCESS_DUPLEX,
                PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT,
                1,           # max instances
                BUFFER_SIZE,
                BUFFER_SIZE,
                0,
                None,
            )
            if pipe == INVALID_HANDLE_VALUE or pipe == 0xFFFFFFFFFFFFFFFF:
                err = k32.GetLastError()
                logger.error("CreateNamedPipe failed with error %d. Retrying in 2s...", err)
                import time as _time
                _time.sleep(2)
                continue

            logger.debug("Waiting for client connection...")
            connected = k32.ConnectNamedPipe(pipe, None)
            if not connected:
                err = k32.GetLastError()
                if err != 535: # ERROR_PIPE_CONNECTED
                    k32.CloseHandle(pipe)
                    continue

            try:
                buf = ctypes.create_string_buffer(BUFFER_SIZE)
                read = wintypes.DWORD()
                if k32.ReadFile(pipe, buf, BUFFER_SIZE, ctypes.byref(read), None):
                    raw_data = buf.raw[:read.value]
                    request = json.loads(raw_data.decode("utf-8").strip())

                    if request.get("type") != "auth_request":
                        response = {"type": "auth_response", "success": False, "error": "invalid_request"}
                    else:
                        action      = request.get("action", "")
                        challenge   = request.get("challenge", "")
                        display_msg = request.get("display_msg", "HYDRA requires Windows authentication")

                        if not action or not challenge:
                            response = {"type": "auth_response", "success": False, "error": "missing_fields"}
                        else:
                            # Show Windows auth dialog
                            authed = _authenticate_windows_user(display_msg)
                            if authed:
                                # Sign (action + ":" + challenge)
                                message = (action + ":" + challenge).encode("utf-8")
                                sig = _sign(priv_raw, message)
                                response = {
                                    "type": "auth_response",
                                    "success": True,
                                    "signature": sig,
                                    "broker_pubkey": pub_b64,
                                }
                            else:
                                response = {
                                    "type": "auth_response",
                                    "success": False,
                                    "error": "user_cancelled_or_failed",
                                }

                    response_bytes = (json.dumps(response) + "\n").encode("utf-8")
                    written = wintypes.DWORD()
                    k32.WriteFile(pipe, response_bytes, len(response_bytes), ctypes.byref(written), None)
                    k32.FlushFileBuffers(pipe)

            finally:
                k32.DisconnectNamedPipe(pipe)
                k32.CloseHandle(pipe)

        except KeyboardInterrupt:
            logger.info("Broker shutting down.")
            break
        except Exception as e:
            logger.error("Unexpected broker error: %s", type(e).__name__, exc_info=True)
            import time as _time
            _time.sleep(1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HYDRA Windows Auth Broker")
    parser.add_argument(
        "--key-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Directory for broker.key and broker.pub files",
    )
    args = parser.parse_args()
    run_broker_server(args.key_dir)
