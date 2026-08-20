# Embedded Connect — reference demo (Acme SaaS)

Shareable **Tier A + Model B** proof: a minimal partner stack (FastAPI + React/Vite) that connects real Gmail accounts through AgentRuntime BFF using a PAT — no end-user AgentRuntime login.

This demo implements the **partner side** of [Embedded Connect](https://github.com/agentruntime-io/agentruntime-docs/blob/main/integrations/embedded-connect.md).

## What it proves

| Step | Who | What happens |
|------|-----|--------------|
| 1 | Partner React app | User clicks **Connect Gmail** |
| 2 | Partner FastAPI | `POST /api/connect/link` → proxies BFF `POST /v1/connect/link` |
| 3 | Partner React app | Opens **hosted connect URL on BFF** (`/connect/s/{session_id}`) — AgentRuntime **Google × AgentRuntime** interstitial |
| 4 | End user | Clicks **Continue to Google** → Google OAuth in same popup |
| 5 | BFF + Control | OAuth callback completes; principal-scoped connection stored in Vault |
| 6 | End user | Google consent (Model B if tenant BYO OAuth configured) |
| 7 | AgentRuntime | `connection.created` webhook (HMAC) to partner URL |
| 8 | Partner FastAPI | Verifies webhook → updates local customer row + inbox UI |

## Prerequisites

1. **AgentRuntime backends** running (BFF on `http://localhost:8080`, Control on `8002`) — localprod or your hosted stack.
2. **Migration `000034_embedded_connect`** applied to Control DB.
3. **Google connect enabled** on your workspace (platform or tenant Model B BYO OAuth).
4. **PAT** (server-side only) — Console → Settings → API keys:
   - **Embedded Connect (connect only)** — `mcp:read`, `mcp:write` — enough for this demo (`POST /v1/connect/link`, `PUT /v1/embedded-connect/settings`, webhooks).
   - **Embedded Connect** — adds `workflow:run`, `mcp:execute` when you also execute workflows per `external_user_id`.
5. **Google Cloud OAuth redirect URI** — add to your OAuth app (Model B) or platform app:

   ```text
   http://localhost:8080/connect/callback
   ```

6. Python 3.11+ and Node 20+.

## Quick start

Clone this repo, then run backend and frontend in separate terminals:

```powershell
git clone https://github.com/agentruntime-io/embedded-example.git
cd embedded-example
```

### 1. Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
# Edit .env — set AGENTRUNTIME_PAT
uvicorn main:app --reload --port 8090
```

### 2. Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open **http://localhost:5175** — fake partner app **Acme SaaS**.

### 3. Try it

1. Confirm green banner: PAT + Google connect enabled.
2. Click **Connect Gmail** for Alice, Bob, or Carol.
3. Complete Google consent in the popup.
4. See **Webhook inbox** receive `connection.created` with `external_user_id` + `connection_id`.
5. Customer row shows connected Gmail + connection ID.

## Environment variables

| Variable | Description |
|----------|-------------|
| `AGENTRUNTIME_BFF_URL` | BFF base URL (default `http://localhost:8080`) |
| `AGENTRUNTIME_PAT` | Server-only PAT — **never** put in React; scopes `mcp:read` + `mcp:write` minimum |
| `DEMO_BACKEND_PUBLIC_URL` | Public URL for **webhook delivery** (`/api/webhooks/agentruntime`), not OAuth |
| `DEMO_WEBHOOK_SECRET` | HMAC secret registered via `PUT /v1/embedded-connect/settings` |
| `DEMO_FRONTEND_ORIGINS` | Allowed postMessage origins from BFF-hosted connect popup |

## Architecture (this repo)

```text
embedded-example/
  backend/          FastAPI — partner API (PAT calls + webhook receiver; no OAuth UI)
  frontend/         Vite React — partner UI (opens BFF popup; no PAT)
  README.md
```

**Partner vs AgentRuntime:** `cust_alice`, `cust_bob`, `cust_carol` live in partner SQLite for the demo UI. AgentRuntime creates matching principals and connections in Control; webhooks carry the canonical `principal_id` and `connection_id`.

```mermaid
flowchart LR
  UI[React 5175] -->|POST /api/connect/link| API[Partner FastAPI 8090]
  API -->|PAT POST /v1/connect/link| BFF[AgentRuntime BFF 8080]
  UI -->|popup connect_url| BFF
  BFF -->|interstitial Continue| BFF
  BFF -->|OAuth| Google[Google]
  Google -->|callback /connect/callback| BFF
  BFF -->|HMAC webhook connection.created| API
  UI -->|GET /api/customers| API
```

## Sharing with customers

1. Share the repo: **[github.com/agentruntime-io/embedded-example](https://github.com/agentruntime-io/embedded-example)** (or fork it for their org).
2. They clone, copy `backend/.env.example` → `backend/.env`, and add their PAT + Google redirect URI (see [Quick start](#quick-start)).
3. Walk through popup + webhook — mirrors production Tier A integration.
4. Point them to [Embedded Connect product docs](https://github.com/agentruntime-io/agentruntime-docs/blob/main/integrations/embedded-connect.md).

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `AGENTRUNTIME_PAT is not set` | Create `backend/.env` from `.env.example` |
| Google connect not enabled | Start BFF/control; configure Google acquisition in sysadmin or tenant BYO |
| OAuth redirect mismatch | Add `http://localhost:8080/connect/callback` to your tenant **Google OAuth application** (Settings → MCP → Google OAuth) in Google Cloud Console |
| 401/403 from BFF | PAT expired or missing connection scopes; recreate PAT |
| Same Gmail on two demo users merges | Use different Google accounts per demo customer, or enable separate grants in platform |

## License

Reference demo for AgentRuntime Embedded Connect — published at [embedded-example](https://github.com/agentruntime-io/embedded-example).
