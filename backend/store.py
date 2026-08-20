"""
Partner-local persistence for the demo (SQLite).

Partner responsibility:
  - Your production database: map `external_id` (your user/customer key) to connection state
    you need for billing, UI, and workflow triggers. AgentRuntime does not replace your user store.

AgentRuntime responsibility:
  - Canonical principals, connections, OAuth tokens (Vault), and webhook delivery.
  - Returns `principal_id` and `connection_id` via connect/link response and webhooks.

This file is demo-only convenience — partners typically use Postgres/MySQL/etc., not this schema.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path(__file__).resolve().parent / "demo_partner.db"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(
            """
            -- Partner customers keyed by external_user_id (e.g. cust_alice).
            -- Production: your users/accounts table; connection_id mirrors AgentRuntime after webhook.
            CREATE TABLE IF NOT EXISTS principals (
                id TEXT PRIMARY KEY,
                external_id TEXT NOT NULL UNIQUE,
                display_name TEXT,
                connection_id TEXT,
                google_email TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            -- Legacy demo table (Tier A uses BFF-hosted sessions; kept for reference helpers).
            CREATE TABLE IF NOT EXISTS connect_sessions (
                id TEXT PRIMARY KEY,
                principal_id TEXT NOT NULL,
                external_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                services_json TEXT NOT NULL,
                oauth_state TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                expires_at TEXT NOT NULL,
                used_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (principal_id) REFERENCES principals(id)
            );

            -- Audit log of inbound webhooks (production: optional queue/dead-letter, not required).
            CREATE TABLE IF NOT EXISTS webhook_events (
                id TEXT PRIMARY KEY,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                received_at TEXT NOT NULL
            );
            """
        )


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def upsert_principal(external_id: str, display_name: str | None = None) -> dict[str, Any]:
    now = _utcnow()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM principals WHERE external_id = ?", (external_id,)
        ).fetchone()
        if row:
            return dict(row)
        pid = f"prin_{uuid.uuid4().hex[:12]}"
        conn.execute(
            """
            INSERT INTO principals (id, external_id, display_name, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (pid, external_id, display_name, now, now),
        )
        return {
            "id": pid,
            "external_id": external_id,
            "display_name": display_name,
            "connection_id": None,
            "google_email": None,
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }


def list_principals() -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM principals ORDER BY created_at ASC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_principal_by_external_id(external_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM principals WHERE external_id = ?", (external_id,)
        ).fetchone()
        return dict(row) if row else None


def sync_platform_principal(external_id: str, platform_principal_id: str) -> None:
    """Replace local placeholder id with AgentRuntime principal_id from link/webhook."""
    now = _utcnow()
    with connect() as conn:
        conn.execute(
            """
            UPDATE principals
            SET id = ?, updated_at = ?
            WHERE external_id = ?
            """,
            (platform_principal_id, now, external_id),
        )


def update_principal_connection(
    external_id: str,
    connection_id: str,
    google_email: str | None,
) -> None:
    """Persist connection.created webhook fields into partner DB."""
    now = _utcnow()
    with connect() as conn:
        conn.execute(
            """
            UPDATE principals
            SET connection_id = ?, google_email = ?, updated_at = ?
            WHERE external_id = ?
            """,
            (connection_id, google_email, now, external_id),
        )


def create_connect_session(
    principal_id: str,
    external_id: str,
    provider: str,
    services: list[str],
    ttl_minutes: int = 5,
) -> dict[str, Any]:
    now = _utcnow()
    expires = (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).isoformat()
    sid = f"cs_{uuid.uuid4().hex[:16]}"
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO connect_sessions
            (id, principal_id, external_id, provider, services_json, status, expires_at, created_at)
            VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)
            """,
            (sid, principal_id, external_id, provider, json.dumps(services), expires, now),
        )
    return {
        "id": sid,
        "principal_id": principal_id,
        "external_id": external_id,
        "provider": provider,
        "services": services,
        "expires_at": expires,
    }


def get_connect_session(session_id: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM connect_sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["services"] = json.loads(data.pop("services_json"))
        return data


def bind_session_oauth_state(session_id: str, oauth_state: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE connect_sessions SET oauth_state = ? WHERE id = ?",
            (oauth_state, session_id),
        )


def complete_connect_session(session_id: str) -> None:
    now = _utcnow()
    with connect() as conn:
        conn.execute(
            """
            UPDATE connect_sessions
            SET status = 'completed', used_at = ?
            WHERE id = ?
            """,
            (now, session_id),
        )


def find_session_by_oauth_state(oauth_state: str) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM connect_sessions WHERE oauth_state = ?", (oauth_state,)
        ).fetchone()
        if not row:
            return None
        data = dict(row)
        data["services"] = json.loads(data.pop("services_json"))
        return data


def session_is_valid(session: dict[str, Any]) -> bool:
    if session.get("status") != "pending":
        return False
    expires = datetime.fromisoformat(session["expires_at"])
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) < expires


def append_webhook_event(event_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    eid = f"evt_{uuid.uuid4().hex[:12]}"
    now = _utcnow()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO webhook_events (id, event_type, payload_json, received_at)
            VALUES (?, ?, ?, ?)
            """,
            (eid, event_type, json.dumps(payload), now),
        )
    return {"id": eid, "event_type": event_type, "payload": payload, "received_at": now}


def list_webhook_events(limit: int = 50) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM webhook_events
            ORDER BY received_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["payload"] = json.loads(d.pop("payload_json"))
            out.append(d)
        return out
