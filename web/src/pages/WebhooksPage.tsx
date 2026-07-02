import React, { useEffect, useMemo, useState } from "react";

import { api } from "../lib/api";
import { formatWhen } from "../lib/format";
import { EmptyState, TextInput } from "../components/common";
import type { Page, Tenant, WebhookEvent, WebhookFilters } from "../types";

const PAGE_SIZE = 25;

function buildWebhookListPath(filters: WebhookFilters, page: number) {
  const params = new URLSearchParams({ page: String(page), page_size: String(PAGE_SIZE) });
  if (filters.search.trim()) params.set("search", filters.search.trim());
  if (filters.status) params.set("status", filters.status);
  if (filters.reason.trim()) params.set("reason", filters.reason.trim());
  if (filters.typeWebhook.trim()) params.set("type_webhook", filters.typeWebhook.trim());
  if (filters.messageId.trim()) params.set("provider_message_id", filters.messageId.trim());
  if (filters.pollId.trim()) params.set("poll_id", filters.pollId.trim());
  if (filters.dateFrom) params.set("date_from", filters.dateFrom);
  if (filters.dateTo) params.set("date_to", filters.dateTo);
  return `/webhooks?${params.toString()}`;
}

function prettyPayload(payloadJson: string) {
  try {
    return JSON.stringify(JSON.parse(payloadJson), null, 2);
  } catch {
    return payloadJson;
  }
}

function statusLabel(status?: string | null) {
  if (status === "accepted") return "Accepted";
  if (status === "ignored") return "Ignored";
  if (status === "error") return "Error";
  return "Received";
}

function statusClassName(status?: string | null) {
  if (status === "accepted") return "pill success";
  if (status === "ignored") return "pill warning";
  if (status === "error") return "pill danger";
  return "pill";
}

export function WebhooksPage({
  tenant,
  onOpenPoll,
}: {
  tenant: Tenant;
  onOpenPoll: (pollId: number) => void;
}) {
  const [filters, setFilters] = useState<WebhookFilters>({
    search: "",
    status: "",
    reason: "",
    typeWebhook: "",
    messageId: "",
    pollId: "",
    dateFrom: "",
    dateTo: "",
  });
  const [page, setPage] = useState(1);
  const [result, setResult] = useState<Page<WebhookEvent>>({
    items: [],
    total: 0,
    page: 1,
    page_size: PAGE_SIZE,
    has_next: false,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retryingId, setRetryingId] = useState<number | null>(null);
  const [refreshNonce, setRefreshNonce] = useState(0);

  const listPath = useMemo(() => buildWebhookListPath(filters, page), [filters, page]);

  useEffect(() => {
    setPage(1);
  }, [filters.search, filters.status, filters.reason, filters.typeWebhook, filters.messageId, filters.pollId, filters.dateFrom, filters.dateTo]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    api<Page<WebhookEvent>>(listPath)
      .then((next) => {
        if (!cancelled) setResult(next);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load webhooks");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [listPath, tenant.id, refreshNonce]);

  async function retryWebhook(webhookId: number) {
    setRetryingId(webhookId);
    setError("");
    try {
      await api<{ ok: boolean; retried: boolean }>(`/webhooks/${webhookId}/retry`, { method: "POST" });
      setRefreshNonce((current) => current + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to retry webhook");
    } finally {
      setRetryingId(null);
    }
  }

  return (
    <section className="resource-page">
      <div className="section-header">
        <div>
          <p className="section-kicker">Webhook Inbox</p>
          <h2>Review incoming WhatsApp webhook events</h2>
        </div>
        <span className="pill">{result.total} stored</span>
      </div>

      <div className="toolbar learner-toolbar">
        <TextInput label="Search" value={filters.search} onChange={(value) => setFilters((current) => ({ ...current, search: value }))} placeholder="Payload, message ID, type, or reason" />
        <label>
          Status
          <select value={filters.status} onChange={(event) => setFilters((current) => ({ ...current, status: event.target.value as WebhookFilters["status"] }))}>
            <option value="">All statuses</option>
            <option value="accepted">Accepted</option>
            <option value="ignored">Ignored</option>
            <option value="error">Error</option>
          </select>
        </label>
        <TextInput label="Reason" value={filters.reason} onChange={(value) => setFilters((current) => ({ ...current, reason: value }))} placeholder="handled or ignored reason" />
        <TextInput label="typeWebhook" value={filters.typeWebhook} onChange={(value) => setFilters((current) => ({ ...current, typeWebhook: value }))} placeholder="incomingMessageReceived" />
        <TextInput label="Message ID" value={filters.messageId} onChange={(value) => setFilters((current) => ({ ...current, messageId: value }))} placeholder="Provider message ID" />
        <TextInput label="Poll ID" value={filters.pollId} onChange={(value) => setFilters((current) => ({ ...current, pollId: value }))} placeholder="123" />
        <TextInput label="From" type="date" value={filters.dateFrom} onChange={(value) => setFilters((current) => ({ ...current, dateFrom: value }))} />
        <TextInput label="To" type="date" value={filters.dateTo} onChange={(value) => setFilters((current) => ({ ...current, dateTo: value }))} />
        <button
          className="button button-ghost"
          onClick={() =>
            setFilters({
              search: "",
              status: "",
              reason: "",
              typeWebhook: "",
              messageId: "",
              pollId: "",
              dateFrom: "",
              dateTo: "",
            })
          }
        >
          Clear filters
        </button>
      </div>

      {error && <div className="alert error">{error}</div>}

      {loading ? (
        <EmptyState title="Loading webhook inbox" body="Fetching tenant-scoped webhook events." />
      ) : result.items.length === 0 ? (
        <EmptyState title="No matching webhooks" body="Adjust the filters or wait for connector callbacks to arrive." />
      ) : (
        <>
          <div className="resource-grid">
            {result.items.map((event) => (
              <article className="resource-card webhook-card" key={event.id}>
                <div className="resource-topline">
                  <span className="resource-id">Webhook #{event.id}</span>
                  <span className={statusClassName(event.decision_status)}>{statusLabel(event.decision_status)}</span>
                </div>
                <div className="meta-row">
                  <span>{event.provider.toUpperCase()}</span>
                  <span>{event.endpoint_path}</span>
                </div>
                <h3>{event.type_webhook || "Unknown typeWebhook"}</h3>
                <div className="meta-row">
                  <span>Received {formatWhen(event.received_at)}</span>
                  <span>{event.message_type || "No typeMessage"}</span>
                </div>
                <div className="meta-row">
                  <span>{event.decision_reason || "No decision reason"}</span>
                  <span>{event.provider_message_id || event.greenapi_message_id || "No message ID"}</span>
                </div>
                <div className="meta-row">
                  <span>Retries {event.retry_count || 0}</span>
                  <span>{event.last_retry_at ? `Last retry ${formatWhen(event.last_retry_at)}` : "No retry yet"}</span>
                </div>
                {event.last_retry_error && <div className="alert warning">{event.last_retry_error}</div>}
                <div className="card-actions">
                  {event.poll_id ? (
                    <button className="button button-ghost" onClick={() => onOpenPoll(event.poll_id || 0)}>
                      Poll #{event.poll_id}
                    </button>
                  ) : (
                    <span className="pill">No linked poll</span>
                  )}
                  {event.decision_status !== "accepted" && (
                    <button className="button button-ghost" onClick={() => retryWebhook(event.id)} disabled={retryingId === event.id}>
                      {retryingId === event.id ? "Retrying..." : "Retry"}
                    </button>
                  )}
                  {event.error && <span className="pill danger">{event.error}</span>}
                </div>
                <details className="payload-viewer">
                  <summary>Exact payload</summary>
                  <pre>{prettyPayload(event.payload_json)}</pre>
                </details>
              </article>
            ))}
          </div>

          <div className="pagination-row">
            <button className="button button-ghost" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={page <= 1}>
              Previous
            </button>
            <span className="meta-inline">
              Page {result.page} · {result.total} events
            </span>
            <button className="button button-ghost" onClick={() => setPage((current) => current + 1)} disabled={!result.has_next}>
              Next
            </button>
          </div>
        </>
      )}
    </section>
  );
}
