# Acme SaaS — partner frontend (Embedded Connect demo)

Minimal React/Vite UI that shows the **partner product surface** for [Embedded Connect Tier A](https://github.com/agentruntime/agentruntime/blob/main/agentruntime-docs/integrations/embedded-connect.md): your end users connect Gmail through a hosted popup while credentials stay on your server.

Full stack setup, prerequisites, and architecture: [../README.md](../README.md).

## What this UI demonstrates

- A **customer list** keyed by your `external_user_id` (demo: Alice, Bob, Carol).
- **Connect Gmail** — opens AgentRuntime’s hosted connect flow in a popup.
- **Webhook inbox** — read-only view of `connection.created` events your backend received (HMAC-verified server-side).
- **Health banner** — confirms partner backend has PAT + Google connect enabled before you test.

This is not AgentRuntime Console. It mimics how *your* SaaS would expose connect to tenants.

## What this UI must NEVER do

| Do not | Why |
|--------|-----|
| Store or read `AGENTRUNTIME_PAT` in the browser | PAT is server-only; exposure compromises your workspace |
| Call AgentRuntime BFF (`/v1/...`) directly from React | All BFF traffic goes through **your** backend with the PAT |
| Handle Google OAuth tokens in the frontend | OAuth completes in the hosted popup; you store `connection_id` from webhooks |

## Connect flow (browser ↔ your backend ↔ AgentRuntime)

```text
1. User clicks "Connect Gmail" for external_user_id cust_alice
2. React POST /api/connect/link  →  partner FastAPI (8090)  →  BFF POST /v1/connect/link (PAT)
3. React window.open(connect_url) — hosted connect page on BFF
4. User completes Google OAuth in popup
5. Popup postMessage({ type: "agentruntime-connect", ... }) to this origin
6. React refreshes /api/customers (also polls every 5s for webhook-driven updates)
7. Partner backend receives connection.created webhook → updates DB → UI shows connection_id
```

## Run locally

Requires the [partner backend](../backend/) on port **8090** (see parent README).

```powershell
cd dev_tools\embedded-connect-demo\frontend
npm install
npm run dev
```

Open **http://localhost:5175**.

During development, Vite proxies `/api/*` to `http://localhost:8090` so fetches stay same-origin and the PAT never enters the bundle.

## Key files

| File | Role |
|------|------|
| `src/App.tsx` | Customer list, connect button, postMessage listener, polling refresh |
| `vite.config.ts` | Dev server port 5175 + `/api` proxy to partner backend |
