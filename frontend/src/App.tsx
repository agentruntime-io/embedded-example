/**
 * Partner frontend — Embedded Connect Tier A example
 *
 * This React app is the **partner product surface** (fake "Acme SaaS"). It shows how
 * your customers connect Gmail without ever touching AgentRuntime credentials in the browser.
 *
 * Identity model (three IDs partners must keep straight):
 * - **Customer** — a row in your product (display name, local DB id). Demo rows are Alice/Bob/Carol.
 * - **external_user_id** — your stable tenant-scoped key for AgentRuntime (e.g. `cust_alice`).
 *   Passed to POST /api/connect/link; echoed in webhooks and postMessage.
 * - **connection_id** — AgentRuntime's id for the OAuth grant once connect succeeds.
 *   Store this server-side; use it for MCP/workflow calls scoped to that customer.
 *
 * All API calls use relative `/api/*` paths. Vite proxies those to the partner FastAPI
 * backend (port 8090), which holds the PAT and talks to AgentRuntime BFF. The browser
 * must never call BFF directly or store a PAT.
 *
 * Connect flow: button → POST /api/connect/link → window.open(connect_url) → hosted popup
 * on BFF → Google OAuth → popup posts `agentruntime-connect` via postMessage → refresh.
 *
 * Polling: we refresh customers/webhooks every 5s because the platform webhook may arrive
 * at your backend before postMessage or before the user closes the popup.
 */

import { useCallback, useEffect, useState } from "react";

type Customer = {
  id: string;
  external_id: string;
  display_name: string | null;
  connection_id: string | null;
  google_email: string | null;
  status: string;
};

type WebhookEvent = {
  id: string;
  event_type: string;
  payload: Record<string, unknown>;
  received_at: string;
};

type Health = {
  ok: boolean;
  bff_url: string;
  pat_configured: boolean;
  google_connect_enabled: boolean;
  google_config_error: string | null;
};

/** Payload from the hosted connect popup (allowed origins configured on partner backend). */
type ConnectMessage = {
  type: string;
  ok: boolean;
  message: string;
  data?: {
    external_user_id?: string;
    connection_id?: string;
    google_email?: string;
  };
};

async function fetchJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

export default function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [events, setEvents] = useState<WebhookEvent[]>([]);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  /** Load health, customer rows, and webhook inbox from partner backend (/api → Vite proxy). */
  const refresh = useCallback(async () => {
    const results = await Promise.allSettled([
      fetchJson<Health>("/api/health"),
      fetchJson<Customer[]>("/api/customers"),
      fetchJson<WebhookEvent[]>("/api/webhooks/events"),
    ]);
    if (results[0].status === "fulfilled") setHealth(results[0].value);
    if (results[1].status === "fulfilled") setCustomers(results[1].value);
    if (results[2].status === "fulfilled") setEvents(results[2].value);
  }, []);

  // Poll so UI catches webhook-driven updates even if postMessage is missed or delayed.
  useEffect(() => {
    void refresh();
    const id = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(id);
  }, [refresh]);

  // Hosted connect popup notifies opener when OAuth finishes (type: agentruntime-connect).
  useEffect(() => {
    const onMessage = (ev: MessageEvent) => {
      const data = ev.data as ConnectMessage;
      if (!data || data.type !== "agentruntime-connect") return;
      if (data.ok) {
        setToast(`Connected ${data.data?.google_email ?? data.data?.external_user_id ?? ""}`);
      } else {
        setToast(`Connect failed: ${data.message}`);
      }
      void refresh();
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [refresh]);

  /** Ask partner backend for a hosted connect URL; open popup (no tokens in this app). */
  const connectGmail = async (externalUserId: string) => {
    setBusyId(externalUserId);
    setToast(null);
    try {
      const link = await fetchJson<{
        connect_url: string;
      }>("/api/connect/link", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ external_user_id: externalUserId, provider: "gmail" }),
      });
      window.open(
        link.connect_url,
        "agentruntime-connect",
        "width=520,height=720,noopener",
      );
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Connect link failed");
    } finally {
      setBusyId(null);
    }
  };

  /**
   * Onboarding banner — guides partners through local setup before trying connect.
   * States: missing PAT → Google connect disabled on BFF → ready.
   */
  const healthBanner = () => {
    if (!health) return null;
    if (!health.pat_configured) {
      return (
        <div className="banner err">
          Set <code>AGENTRUNTIME_PAT</code> in <code>backend/.env</code> and restart the
          FastAPI server.
        </div>
      );
    }
    if (!health.google_connect_enabled) {
      return (
        <div className="banner warn">
          Google connect is not enabled on BFF ({health.bff_url}). Start localprod backends
          and configure Google acquisition / tenant BYO OAuth.{" "}
          {health.google_config_error ? `(${health.google_config_error})` : null}
        </div>
      );
    }
    return (
      <div className="banner ok">
        Ready — BFF {health.bff_url}, PAT configured, Google connect enabled.
      </div>
    );
  };

  return (
    <div className="app">
      <header>
        <h1>Acme SaaS</h1>
        <p>
          Demo partner app — your customers connect Gmail via AgentRuntime Embedded Connect
          (Tier A + Model B).
        </p>
      </header>

      {healthBanner()}
      {toast ? <div className="banner ok">{toast}</div> : null}

      <div className="grid">
        <section className="card">
          <h2>Your customers</h2>
          <p style={{ margin: "0 0 1rem", color: "#64748b", fontSize: "0.9rem" }}>
            Each row is a partner <code>external_user_id</code>. Connect opens a hosted popup;
            your backend never sees Google tokens.
          </p>
          {customers.map((c) => (
            <div className="customer" key={c.external_id}>
              <div className="customer-meta">
                <strong>{c.display_name ?? c.external_id}</strong>
                <code>{c.external_id}</code>
                {c.connection_id ? (
                  <div style={{ marginTop: "0.25rem" }}>
                    <span className="badge connected">{c.google_email ?? "Connected"}</span>
                    <code style={{ marginLeft: "0.5rem", fontSize: "0.75rem" }}>
                      {c.connection_id}
                    </code>
                  </div>
                ) : (
                  <span className="badge" style={{ marginTop: "0.25rem" }}>
                    Not connected
                  </span>
                )}
              </div>
              {c.connection_id ? (
                <button
                  type="button"
                  className="secondary"
                  disabled={busyId === c.external_id}
                  onClick={() => void connectGmail(c.external_id)}
                  title="Start a new connect session (e.g. switch Google account)"
                >
                  {busyId === c.external_id ? "Opening…" : "Reconnect"}
                </button>
              ) : (
                <button
                  type="button"
                  disabled={busyId === c.external_id}
                  onClick={() => void connectGmail(c.external_id)}
                >
                  {busyId === c.external_id ? "Opening…" : "Connect Gmail"}
                </button>
              )}
            </div>
          ))}
          <div className="actions">
            <button type="button" className="secondary" onClick={() => void refresh()}>
              Refresh
            </button>
          </div>
        </section>

        <section className="card">
          <h2>Webhook inbox</h2>
          <p style={{ margin: "0 0 1rem", color: "#64748b", fontSize: "0.9rem" }}>
            Simulates <code>connection.created</code> delivered to your server with HMAC
            signature verification.
          </p>
          <div className="events">
            {events.length === 0 ? (
              <p style={{ color: "#94a3b8" }}>No events yet. Connect a customer to see webhooks.</p>
            ) : (
              events.map((ev) => (
                <div className="event" key={ev.id}>
                  <strong>{ev.event_type}</strong>{" "}
                  <time>{new Date(ev.received_at).toLocaleString()}</time>
                  <pre>{JSON.stringify(ev.payload, null, 2)}</pre>
                </div>
              ))
            )}
          </div>
        </section>
      </div>
    </div>
  );
}
