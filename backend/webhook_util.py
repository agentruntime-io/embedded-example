"""
HMAC verification for AgentRuntime inbound webhooks.

Partner responsibility:
  - Verify `X-Agentruntime-Signature` on every inbound POST before parsing JSON.
  - Store `webhook_secret` securely; register the same value via PUT /v1/embedded-connect/settings.
  - Reject replay/forged requests — unsigned or wrong-signature payloads must not update your DB.

AgentRuntime responsibility:
  - Sign each webhook with HMAC-SHA256 over `{timestamp}.{raw_body}` (header: `t=…,v1=…`).

Why it matters: your webhook URL is a public endpoint. Without verification, an attacker could
POST fake `connection.created` events and mark users as connected when they are not.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any

WEBHOOK_SECRET = os.getenv("DEMO_WEBHOOK_SECRET", "dev-webhook-secret-change-me")


def sign_payload(payload: dict[str, Any]) -> str:
    """Demo helper to synthesize a valid signature (AgentRuntime signs in production)."""
    ts = str(int(time.time()))
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    msg = f"{ts}.{body}".encode("utf-8")
    sig = hmac.new(WEBHOOK_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return f"t={ts},v1={sig}"


def verify_signature(header: str | None, raw_body: bytes) -> bool:
    if not header:
        return False
    parts: dict[str, str] = {}
    for piece in header.split(","):
        if "=" in piece:
            k, v = piece.strip().split("=", 1)
            parts[k] = v
    ts = parts.get("t")
    v1 = parts.get("v1")
    if not ts or not v1:
        return False
    msg = f"{ts}.{raw_body.decode('utf-8')}".encode("utf-8")
    expected = hmac.new(WEBHOOK_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, v1)
