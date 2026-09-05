# Gmail sync — testing guide

End-to-end test for **bootstrap**, **backfill** (with start date), and **live sync** per Embedded Connect principal.

## Prerequisites

1. **Local stack running** — BFF (`8080`), Control, Gmail connector, Tenant Data (`8040`).
2. **PAT** with `mcp:read`, `mcp:write`, `workflow:run`, `mcp:execute`.
3. **Gmail MCP instance** wired to OAuth (Embedded Connect principal resolution).
4. **Tenant Data MCP instance** bound to a database with schema from [`gmail-tenant-data-schema.json`](./gmail-tenant-data-schema.json).

## Step 1: Create Tenant Data schema

Console → Data → Create database → paste schema from:

```text
dev_tools/embedded-connect-demo/examples/gmail-tenant-data-schema.json
```

Tables created:

| Table | Purpose |
|-------|---------|
| `gmail_sync_state` | Checkpoint + backfill pagination per `external_id` |
| `gmail_threads` | Conversation index |
| `gmail_messages` | Full body + metadata |
| `gmail_attachments` | Metadata + inline bytes (`download_status`: downloaded / skipped_size / failed) |

Note the **database ID** and provision **Tenant Data MCP** instance.

## Step 2: Import workflows and configure platform event triggers

Import these workflow JSON files into Console → Workflows:

| File | Purpose |
|------|---------|
| [`gmail-bootstrap-workflow.json`](./gmail-bootstrap-workflow.json) | On connect: profile → `gmail_sync_state` |
| [`gmail-backfill-workflow.json`](./gmail-backfill-workflow.json) | Historical threads/messages (requires `backfill_after`) |
| [`gmail-live-sync-workflow.json`](./gmail-live-sync-workflow.json) | Incremental history poll |

After import, open each workflow → **Run setup → Events**:

| Workflow | Event | Trigger payload (example) |
|----------|-------|---------------------------|
| gmail-bootstrap-sync | `connection.created` | `{}` |
| gmail-backfill-sync | `connection.created` | `{ "backfill_after": "2026/01/01" }` |

Select an automation API key with `workflow:run` + `mcp:execute`. Platform merges `connection_id`, `synced_at`, and `external_user_id` from the event at fire time.

For live sync, use **Cron** tab with a principal segment (`require_connection`) instead of partner cron.

### Replace placeholders in each workflow

Search/replace in all three files:

| Placeholder | Your value |
|-------------|------------|
| `REPLACE_GMAIL_MCP_INSTANCE_ID` | Gmail MCP catalog instance UUID |
| `REPLACE_TENANTDATA_MCP_INSTANCE_ID` | Tenant Data MCP instance UUID |
| `http://localhost:8080/gmail/mcp` | Your Gmail MCP URL (if not localprod) |
| `http://localhost:8040/mcp` | Your Tenant Data MCP URL |

Copy published **workflow UUIDs** from Console.

## Step 3: Configure demo backend

Copy [`gmail-sync-config.example.json`](./gmail-sync-config.example.json) values into `backend/.env`:

```env
GMAIL_BOOTSTRAP_WORKFLOW_ID=<uuid>
GMAIL_BACKFILL_WORKFLOW_ID=<uuid>
GMAIL_LIVE_SYNC_WORKFLOW_ID=<uuid>
GMAIL_DEFAULT_BACKFILL_AFTER=2026/01/01
GMAIL_POLL_INTERVAL_SECONDS=120
GMAIL_INTERNAL_SYNC_ENABLED=true
GMAIL_MAX_ATTACHMENT_BYTES=5242880
DEMO_ADMIN_SECRET=dev-admin-secret-change-me
```

## Step 4: Connect a test user

1. Start demo backend + frontend (see main README).
2. Click **Connect Gmail** for Alice (`cust_alice`).
3. Complete OAuth.
4. Webhook fires → demo updates local DB. **Bootstrap + backfill** start via Console **platform event** triggers on `connection.created`.
5. **Internal scheduler** starts live sync + backfill continuation every `GMAIL_POLL_INTERVAL_SECONDS` — no embedded UI calls required.

## Step 5: Manual admin triggers (debug only)

These routes are **partner-admin only** (`X-Demo-Admin-Secret` header). Embedded end users must never call sync workflows.

```powershell
$admin = "dev-admin-secret-change-me"

# Bootstrap only
curl -X POST http://localhost:8090/api/admin/sync/bootstrap/cust_alice `
  -H "X-Demo-Admin-Secret: $admin"

# Backfill (with start date — required lower bound)
curl -X POST http://localhost:8090/api/admin/sync/backfill/cust_alice `
  -H "X-Demo-Admin-Secret: $admin" `
  -H "Content-Type: application/json" `
  -d '{"backfill_after": "2026/01/01"}'

# Resume backfill (when gmail_sync_state.backfill_status = running)
curl -X POST http://localhost:8090/api/admin/sync/backfill/cust_alice `
  -H "X-Demo-Admin-Secret: $admin" `
  -H "Content-Type: application/json" `
  -d '{"backfill_after": "2026/01/01", "backfill_page_token": "<token from sync_state>"}'

# One-shot live sync (normally handled by internal scheduler)
curl -X POST http://localhost:8090/api/admin/sync/live/cust_alice `
  -H "X-Demo-Admin-Secret: $admin"
```

Or via BFF directly:

```powershell
curl -X POST http://localhost:8080/v1/workflows/<BACKFILL_WORKFLOW_ID>/command `
  -H "Authorization: Bearer $PAT" `
  -H "Content-Type: application/json" `
  -d '{
    "command": "execute",
    "params": {
      "external_user_id": "cust_alice",
      "trigger_payload": {
        "backfill_after": "2026/01/01",
        "synced_at": "2026-09-02T00:00:00Z"
      }
    }
  }'
```

## Step 6: Verify in Tenant Data

Console → Data → browse tables:

| Check | Table | Filter |
|-------|-------|--------|
| Checkpoint exists | `gmail_sync_state` | `external_id = cust_alice` |
| Threads populated | `gmail_threads` | `external_id = cust_alice` |
| Messages with body | `gmail_messages` | `has_attachments`, `body_text` |
| Attachment bytes | `gmail_attachments` | `download_status = downloaded`, `content_base64` set |
| Oversized attachment | `gmail_attachments` | `download_status = skipped_size` |
| Trash/archive | `gmail_threads` | `is_trashed`, `is_archived` updated on live sync |
| Permanent delete | `gmail_messages` | `is_deleted = true` |
| Backfill done | `gmail_sync_state` | `backfill_status = complete` |

## Backfill pagination loop

Backfill processes **50 threads per run**. When more pages exist:

```text
gmail_sync_state.backfill_status = running
gmail_sync_state.backfill_page_token = <token>
```

Re-run backfill workflow (same `external_user_id`) until `backfill_status = complete`.

Partner cron pattern:

```python
while sync_state["backfill_status"] == "running":
    execute_workflow(BACKFILL_ID, external_user_id, {
        "backfill_after": "2026/01/01",
        "backfill_page_token": sync_state.get("backfill_page_token"),
        "synced_at": utc_now(),
    })
```

## Live sync (internal scheduler)

The demo backend runs **`sync_scheduler.py`** on startup when `GMAIL_INTERNAL_SYNC_ENABLED=true`:

- Every `GMAIL_POLL_INTERVAL_SECONDS`, for each connected principal:
  - `GMAIL_LIVE_SYNC_WORKFLOW_ID` — history poll (new messages, trash/archive, deletes)
  - `GMAIL_BACKFILL_WORKFLOW_ID` — continue pagination when `backfill_status=running`

Embedded users only complete OAuth; they never POST to sync routes. Production: same pattern as a K8s CronJob or worker with your server PAT.

Manual one-shot (admin only):

```powershell
curl -X POST http://localhost:8090/api/admin/sync/live/cust_alice -H "X-Demo-Admin-Secret: $admin"
```

Live sync reads `last_history_id`, calls `gmail_list_history`, handles `messages_added`, `messages_deleted`, `labels_added`/`labels_removed` (TRASH, INBOX), fetches new messages with `gmail_get_email_full`, downloads attachments ≤ `max_attachment_bytes`, advances checkpoint.

## Start date (`backfill_after`)

**Required** — prevents unbounded backfill.

Gmail query built as:

```text
in:inbox after:2026/01/01
```

Override with full query in trigger_payload:

```json
{
  "backfill_after": "2026/06/01",
  "backfill_query": "in:inbox after:2026/06/01 before:2026/09/01"
}
```

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `principal_not_connected` | Complete OAuth first; check `connection_id` in demo DB |
| Workflow 503 | Set `GMAIL_*_WORKFLOW_ID` in `.env` |
| Empty history on live sync | Run bootstrap first; check `last_history_id` in sync_state |
| Duplicate rows | Upsert keys: `(external_id, gmail_id)` — should merge |
| Rate limits | Lower `for_each_max_parallel` (default 3) |
| Attachment rows empty | Normal if messages have no attachments |
| `admin_secret_required` | Add `X-Demo-Admin-Secret` header for `/api/admin/sync/*` |
| Large attachments skipped | Expected when `size_bytes > GMAIL_MAX_ATTACHMENT_BYTES` |

## Architecture reference

See [`connectors/go-connectors/gmail-connector/docs/GMAIL_TENANT_DATA_WORKFLOWS.md`](../../../connectors/go-connectors/gmail-connector/docs/GMAIL_TENANT_DATA_WORKFLOWS.md).
