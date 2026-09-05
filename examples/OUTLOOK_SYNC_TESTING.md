# Outlook sync — testing guide

End-to-end test for **bootstrap**, **backfill** (with start date), and **live sync** per Embedded Connect principal. Cloned from the Gmail Embedded Connect pattern.

## Prerequisites

1. **Local stack running** — BFF (`8080`), Control, Microsoft Outlook connector, Tenant Data (`8040`).
2. **PAT** with `mcp:read`, `mcp:write`, `workflow:run`, `mcp:execute`.
3. **Outlook MCP instance** wired to OAuth (Embedded Connect principal resolution).
4. **Tenant Data MCP instance** bound to a database with schema from [`outlook-tenant-data-schema.json`](./outlook-tenant-data-schema.json).

## Step 1: Create Tenant Data schema

Console → Data → Create database → paste schema from:

```text
dev_tools/embedded-connect-demo/examples/outlook-tenant-data-schema.json
```

Tables:

| Table | Purpose |
|-------|---------|
| `outlook_sync_state` | Checkpoint + backfill pagination per `external_id` |
| `outlook_conversations` | Conversation index (Graph `conversation_id`) |
| `outlook_messages` | Message metadata rows |

## Step 2: Import workflows

| File | Purpose |
|------|---------|
| [`outlook-bootstrap-workflow.json`](./outlook-bootstrap-workflow.json) | On connect: profile + inbox folder → `outlook_sync_state` |
| [`outlook-backfill-workflow.json`](./outlook-backfill-workflow.json) | Historical messages (`backfill_after` required) |
| [`outlook-live-sync-workflow.json`](./outlook-live-sync-workflow.json) | Incremental poll via `receivedDateTime gt last_sync_at` |

### Replace placeholders

| Placeholder | Your value |
|-------------|------------|
| `REPLACE_OUTLOOK_MCP_INSTANCE_ID` | Outlook MCP catalog instance UUID |
| `REPLACE_TENANTDATA_MCP_INSTANCE_ID` | Tenant Data MCP instance UUID |

### Platform event triggers (example)

| Workflow | Event | Trigger payload |
|----------|-------|-----------------|
| outlook-bootstrap-sync | `connection.created` | `{}` |
| outlook-backfill-sync | `connection.created` | `{ "backfill_after": "2026-01-01" }` |

Live sync: **Cron** tab with principal segment (`require_connection`).

## Step 3: Verify in Tenant Data

| Check | Table | Filter |
|-------|-------|--------|
| Checkpoint exists | `outlook_sync_state` | `external_id = cust_alice` |
| Messages populated | `outlook_messages` | `source = backfill` |
| Live rows | `outlook_messages` | `source = live` |
| Backfill done | `outlook_sync_state` | `backfill_status = complete` |

## Tools used

- `microsoft_outlook_graph_request` — profile (`GET me`)
- `microsoft_outlook_list_mail_folders` — resolve Inbox folder id
- `microsoft_outlook_list_messages` — paginated listing with OData `$filter`
- `microsoft_outlook_get_message` — full message metadata per id

## Backfill start date

**Required** — `backfill_after` ISO date (e.g. `2026-01-01`) becomes OData filter:

```text
receivedDateTime ge 2026-01-01T00:00:00Z
```

Re-run backfill while `outlook_sync_state.backfill_status = running`.

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Empty inbox folder id | Re-run bootstrap; check mail folder list |
| No messages on live sync | Confirm `last_sync_at` in sync_state |
| Duplicate rows | Upsert keys `(external_id, message_id)` |
