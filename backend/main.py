"""
Partner demo backend — Tier A Embedded Connect reference (Acme SaaS).

Partner responsibility:
  - Own HTTP routes your React/mobile app calls (never expose the PAT to the browser).
  - Map your customer IDs (`external_user_id`) to rows in your database.
  - Register webhook URL + HMAC secret via BFF `PUT /v1/embedded-connect/settings`.
  - Verify inbound webhooks before trusting `connection_id` / `principal_id`.

AgentRuntime responsibility:
  - Hosted connect popup at BFF `/connect/s/{session_id}` (OAuth UI + callback).
  - JIT principals, Vault credentials, and principal-scoped connections in Control.
  - Deliver signed `connection.created` webhooks after OAuth completes.

Production mapping (this demo → BFF):
  POST /api/connect/link          → POST /v1/connect/link
  startup webhook registration    → PUT /v1/embedded-connect/settings
  POST /api/webhooks/agentruntime → your public webhook receiver (same path pattern)

Run: uvicorn main:app --reload --port 8090
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import httpx
from dotenv import load_dotenv

# Load backend/.env before any module reads AGENTRUNTIME_* at import time.
load_dotenv(Path(__file__).resolve().parent / ".env")

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import agentruntime_client as ar
import store
from webhook_util import verify_signature

# Public URL AgentRuntime uses to POST webhooks (must be reachable from BFF/control).
BACKEND_PUBLIC = os.getenv("DEMO_BACKEND_PUBLIC_URL", "http://localhost:8090").rstrip("/")
# Origins allowed for postMessage from the BFF-hosted connect popup (your frontend only).
FRONTEND_ORIGINS = [
    o.strip()
    for o in os.getenv(
        "DEMO_FRONTEND_ORIGINS",
        "http://localhost:5175,http://127.0.0.1:5175",
    ).split(",")
    if o.strip()
]
# Shared with AgentRuntime via embedded-connect settings; used to verify inbound webhooks.
WEBHOOK_SECRET = os.getenv("DEMO_WEBHOOK_SECRET", "dev-webhook-secret-change-me")

app = FastAPI(
    title="Acme SaaS — Embedded Connect demo (partner backend)",
    description="Reference Tier A integration: PAT → POST /v1/connect/link → hosted popup → platform webhook",
    version="0.2.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _register_webhook_settings() -> None:
    """Push webhook URL + secret to AgentRuntime (production: run once at deploy or via admin API)."""
    webhook_url = f"{BACKEND_PUBLIC}/api/webhooks/agentruntime"
    try:
        await ar.configure_embedded_connect_settings(
            webhook_url,
            WEBHOOK_SECRET,
            allowed_origins=FRONTEND_ORIGINS,
        )
    except (ar.AgentRuntimeError, asyncio.TimeoutError, httpx.TimeoutException):
        pass


@app.on_event("startup")
async def on_startup() -> None:
    store.init_db()
    # Three seeded demo customers — in production these are rows in *your* DB keyed by your user IDs.
    # AgentRuntime creates matching principals JIT on first connect/link; we mirror them locally for the UI.
    if not store.list_principals():
        for ext, name in [
            ("cust_alice", "Alice (demo)"),
            ("cust_bob", "Bob (demo)"),
            ("cust_carol", "Carol (demo)"),
        ]:
            store.upsert_principal(ext, name)

    # Do not block request handling on BFF webhook registration.
    asyncio.create_task(_register_webhook_settings())


class ConnectLinkRequest(BaseModel):
    external_user_id: str = Field(..., min_length=1, max_length=256)
    provider: str = Field(default="gmail")
    services: list[str] | None = None


class ConnectLinkResponse(BaseModel):
    connect_url: str
    connect_session_id: str
    expires_at: str
    external_user_id: str
    principal_id: str


# --- Health ---


@app.get("/api/health")
async def health() -> dict[str, Any]:
    """Demo diagnostics: PAT present, Google connect enabled, webhook URL we registered."""
    cfg_ok = False
    cfg_error: str | None = None
    try:
        cfg = await asyncio.wait_for(ar.google_connect_config(), timeout=5.0)
        cfg_ok = bool(cfg.get("enabled"))
    except (ar.AgentRuntimeError, asyncio.TimeoutError, httpx.TimeoutException) as exc:
        cfg_error = str(exc)
    return {
        "ok": True,
        "bff_url": os.getenv("AGENTRUNTIME_BFF_URL", "http://localhost:8080"),
        "pat_configured": bool(os.getenv("AGENTRUNTIME_PAT", "").strip()),
        "google_connect_enabled": cfg_ok,
        "google_config_error": cfg_error,
        "webhook_url": f"{BACKEND_PUBLIC}/api/webhooks/agentruntime",
        "uses_platform_connect_link": True,
    }


# --- Partner customers (local DB; production: your users table) ---


@app.get("/api/customers")
def list_customers() -> list[dict[str, Any]]:
    """Return demo customer rows from partner SQLite — not AgentRuntime's principal API."""
    return store.list_principals()


# --- Connect link (maps to BFF POST /v1/connect/link) ---


@app.post("/api/connect/link", response_model=ConnectLinkResponse)
async def create_connect_link(body: ConnectLinkRequest) -> ConnectLinkResponse:
    """
    Create a hosted connect session. Frontend opens `connect_url` in a popup — that URL is on
    AgentRuntime BFF, not this backend. OAuth never touches the partner server.
    """
    external_id = body.external_user_id.strip()
    principal = store.upsert_principal(external_id)
    try:
        link = await ar.connect_link(
            external_id,
            provider=body.provider,
            services=body.services,
            metadata={"display_name": principal.get("display_name")},
        )
    except ar.AgentRuntimeError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    # AgentRuntime returns the canonical principal_id; sync into our local row for display.
    platform_principal_id = str(link.get("principal_id", ""))
    if platform_principal_id:
        store.sync_platform_principal(external_id, platform_principal_id)

    return ConnectLinkResponse(
        connect_url=str(link["connect_url"]),
        connect_session_id=str(link["connect_session_id"]),
        expires_at=str(link["expires_at"]),
        external_user_id=external_id,
        principal_id=platform_principal_id or principal["id"],
    )


# --- Webhooks (AgentRuntime → partner; verify HMAC before trusting payload) ---


@app.post("/api/webhooks/agentruntime")
async def receive_webhook(request: Request) -> dict[str, str]:
    """
    Inbound webhook receiver. Production: always verify X-Agentruntime-Signature — otherwise
    anyone who guesses your URL could forge connection.created events.
    """
    raw = await request.body()
    sig = request.headers.get("X-Agentruntime-Signature")
    if not verify_signature(sig, raw):
        raise HTTPException(status_code=401, detail="invalid_signature")
    payload = json.loads(raw.decode("utf-8"))
    store.append_webhook_event(payload.get("event", "unknown"), payload)

    if payload.get("event") == "connection.created":
        external_id = str(payload.get("external_user_id", "")).strip()
        connection_id = str(payload.get("connection_id", "")).strip()
        google_email = payload.get("provider_account_key")
        principal_id = payload.get("principal_id")
        if external_id and connection_id:
            store.update_principal_connection(external_id, connection_id, google_email)
        if external_id and principal_id:
            store.sync_platform_principal(external_id, str(principal_id))

    return {"status": "ok"}


@app.get("/api/webhooks/events")
def webhook_events() -> list[dict[str, Any]]:
    """Demo-only inbox so partners can see raw webhook payloads during integration."""
    return store.list_webhook_events()
