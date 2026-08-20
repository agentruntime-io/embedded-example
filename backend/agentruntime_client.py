"""
AgentRuntime BFF client — server-side PAT calls only.

Partner responsibility:
  - Store `AGENTRUNTIME_PAT` in env/secrets manager; attach as `Authorization: Bearer …` here.
  - Never bundle the PAT in frontend code, mobile apps, or browser-accessible config.

AgentRuntime responsibility:
  - Authenticate PAT, enforce scopes, run hosted connect + OAuth, emit webhooks.

All routes below hit `{AGENTRUNTIME_BFF_URL}` (default localprod: http://localhost:8080).
"""

from __future__ import annotations

import os
from typing import Any

import httpx

BFF_URL = os.getenv("AGENTRUNTIME_BFF_URL", "http://localhost:8080").rstrip("/")
# Keep BFF calls short so /api/health and startup never wedge the demo server.
_DEFAULT_TIMEOUT = httpx.Timeout(5.0, connect=3.0)


def _pat() -> str:
    return os.getenv("AGENTRUNTIME_PAT", "").strip()


class AgentRuntimeError(Exception):
    def __init__(self, status_code: int, message: str, body: Any = None):
        super().__init__(message)
        self.status_code = status_code
        self.body = body


def _headers() -> dict[str, str]:
    pat = _pat()
    if not pat:
        raise AgentRuntimeError(
            503,
            "AGENTRUNTIME_PAT is not set. Copy backend/.env.example to backend/.env",
        )
    return {
        "Authorization": f"Bearer {pat}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def google_connect_config() -> dict[str, Any]:
    """GET /v1/connections/google/config — PAT scope: mcp:read"""
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        resp = await client.get(
            f"{BFF_URL}/v1/connections/google/config",
            headers=_headers(),
        )
        if resp.status_code >= 400:
            raise AgentRuntimeError(resp.status_code, resp.text, resp.json() if resp.content else None)
        return resp.json()


async def connect_link(
    external_user_id: str,
    *,
    provider: str = "gmail",
    services: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """POST /v1/connect/link — PAT scope: mcp:write. Returns hosted connect_url on BFF."""
    body: dict[str, Any] = {
        "external_user_id": external_user_id,
        "provider": provider,
        "services": services or ["gmail"],
    }
    if metadata:
        body["metadata"] = metadata
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        resp = await client.post(
            f"{BFF_URL}/v1/connect/link",
            headers=_headers(),
            json=body,
        )
        if resp.status_code >= 400:
            raise AgentRuntimeError(resp.status_code, resp.text, resp.json() if resp.content else None)
        return resp.json()


async def connect_session_status(session_id: str) -> dict[str, Any]:
    """GET /v1/connect/sessions/{id} — PAT scope: mcp:read (optional poll if not using webhooks)."""
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        resp = await client.get(
            f"{BFF_URL}/v1/connect/sessions/{session_id}",
            headers=_headers(),
        )
        if resp.status_code >= 400:
            raise AgentRuntimeError(resp.status_code, resp.text, resp.json() if resp.content else None)
        return resp.json()


async def configure_embedded_connect_settings(
    webhook_url: str,
    webhook_secret: str,
    *,
    allowed_origins: list[str] | None = None,
) -> dict[str, Any]:
    """PUT /v1/embedded-connect/settings — PAT scope: mcp:write. Registers webhook + popup origins."""
    body: dict[str, Any] = {
        "webhook_url": webhook_url,
        "webhook_secret": webhook_secret,
        "enabled": True,
    }
    if allowed_origins:
        body["allowed_origins"] = allowed_origins
    async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT) as client:
        resp = await client.put(
            f"{BFF_URL}/v1/embedded-connect/settings",
            headers=_headers(),
            json=body,
        )
        if resp.status_code >= 400:
            raise AgentRuntimeError(resp.status_code, resp.text, resp.json() if resp.content else None)
        return resp.json()
