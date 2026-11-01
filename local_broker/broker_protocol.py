"""
local_broker/broker_protocol.py
--------------------------------
Named-pipe IPC protocol between the FastAPI server and the Windows-local
authentication broker process.

Security design:
  - All communication is over a LOCAL named pipe (\\.\pipe\HydraAuthBroker)
    inaccessible from the network.
  - Every request includes a one-time challenge nonce.
  - The broker signs {action_bytes + challenge_bytes} with its Ed25519 key.
  - The server verifies the signature against the broker's known public key.
  - Challenges expire after 60 seconds (TTL enforced by the server).
  - Replay prevention: each challenge is single-use (tracked in DB).

Message format: newline-delimited JSON over the pipe.

Request  (server → broker):
  {"type": "auth_request", "action": "<action>", "challenge": "<b64url>",
   "display_msg": "<human-readable message shown in the UAC/CredUI dialog>"}

Response (broker → server):
  {"type": "auth_response", "success": true,
   "signature": "<b64url Ed25519 sig of action+':'+challenge>",
   "broker_pubkey": "<b64url>"}
  OR
  {"type": "auth_response", "success": false, "error": "<reason>"}
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

PIPE_NAME = r"\\.\pipe\HydraAuthBroker"
BUFFER_SIZE = 4096

# Actions that the broker will process
class BrokerAction:
    REGISTER_FIRST_OWNER = "register_first_owner"
    ADD_OWNER            = "add_owner"
    REMOVE_OWNER         = "remove_owner"
    PROMOTE_TO_OWNER     = "promote_to_owner"
    RESET_OWNERSHIP      = "reset_ownership"
    CHANGE_SECURITY_POLICY = "change_security_policy"
    LOCAL_LOGIN          = "local_login"


def encode_message(msg: Dict[str, Any]) -> bytes:
    """Encode a message dict as UTF-8 JSON followed by a newline."""
    return (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")


def decode_message(data: bytes) -> Dict[str, Any]:
    """Decode a UTF-8 JSON message (with optional trailing newline)."""
    return json.loads(data.decode("utf-8").strip())


def make_auth_request(
    action: str,
    challenge: str,
    display_msg: str,
) -> bytes:
    """Build a serialised auth request for the broker."""
    return encode_message({
        "type": "auth_request",
        "action": action,
        "challenge": challenge,
        "display_msg": display_msg,
    })
