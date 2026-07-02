import React, { useEffect, useState } from "react";
import { FilePenLine } from "lucide-react";
import { DetailRow, EmptyState } from "../components/common";
import { api } from "../lib/api";
import type { PilotReadinessResponse, Tenant } from "../types";

function formatWebhookActivity(value?: string | null) {
  if (!value) return "No webhook activity yet";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export function SettingsPage({ tenant, onEdit }: { tenant: Tenant; onEdit: () => void }) {
  const [pilotReadiness, setPilotReadiness] = useState<PilotReadinessResponse | null>(null);
  const [pilotReadinessError, setPilotReadinessError] = useState("");
  const [pilotReadinessLoading, setPilotReadinessLoading] = useState(true);
  const connector = tenant.whatsapp_connector;
  const connectorConfig = connector?.config || {};
  const diagnostics = connector?.diagnostics;
  const isWaha = connector?.provider === "waha";
  const readiness = [
    { label: "Connector provider", ready: Boolean(connector?.provider) },
    { label: isWaha ? "WAHA base URL" : "GreenAPI URL", ready: Boolean(isWaha ? connectorConfig.base_url : connectorConfig.api_url) },
    { label: isWaha ? "WAHA session" : "GreenAPI instance", ready: Boolean(isWaha ? connectorConfig.session : connectorConfig.id_instance) },
    { label: isWaha ? "WAHA API key" : "GreenAPI token", ready: Boolean(isWaha ? connectorConfig.api_key : connectorConfig.api_token_instance) },
    { label: "Gemini API key", ready: Boolean(tenant.gemini_api_key) },
  ];
  const activityRows = [
    { label: "Last webhook", value: formatWebhookActivity(diagnostics?.last_webhook_at) },
    { label: "Latest decision", value: diagnostics?.last_webhook_status || "No webhook activity yet" },
    { label: "Latest reason", value: diagnostics?.last_webhook_reason || "No webhook activity yet" },
    { label: "Webhook volume", value: diagnostics ? `${diagnostics.webhooks_last_24h || 0} in 24h` : "No webhook activity yet" },
    {
      label: "Accepted / ignored / errored",
      value: diagnostics ? `${diagnostics.accepted_last_24h || 0} / ${diagnostics.ignored_last_24h || 0} / ${diagnostics.errored_last_24h || 0}` : "No webhook activity yet",
    },
  ];

  useEffect(() => {
    let cancelled = false;
    setPilotReadinessLoading(true);
    setPilotReadinessError("");
    api<PilotReadinessResponse>("/pilot-readiness")
      .then((result) => {
        if (!cancelled) setPilotReadiness(result);
      })
      .catch((err) => {
        if (!cancelled) setPilotReadinessError(err instanceof Error ? err.message : "Failed to load pilot readiness");
      })
      .finally(() => {
        if (!cancelled) setPilotReadinessLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenant.id]);

  return (
    <section className="detail-page">
      <div className="detail-hero">
        <div>
          <p className="section-kicker">Settings</p>
          <h2>{tenant.name}</h2>
          <p className="hero-subtitle">Tenant creation moved to registration. This page now edits only the current workspace.</p>
        </div>
        <div className="hero-actions">
          <button className="button button-primary" onClick={onEdit}>
            <FilePenLine size={16} /> Edit workspace
          </button>
        </div>
      </div>

      <div className="detail-layout">
        <section className="surface">
          <div className="section-header">
            <div>
              <p className="section-kicker">Configuration</p>
              <h3>Workspace details</h3>
            </div>
          </div>
          <DetailRow label="Username" value={tenant.username} />
          <DetailRow label="Timezone" value={tenant.timezone} />
          <DetailRow label="Scheduler" value={tenant.scheduler_enabled ? "Enabled" : "Disabled"} />
          <DetailRow label="Summaries" value={tenant.summary_enabled ? "Enabled" : "Disabled"} />
          <DetailRow label="Pool target size" value={String(tenant.poll_pool_target_size)} />
          <DetailRow label="Refill batch size" value={String(tenant.poll_pool_refill_batch_size)} />
          <DetailRow label="Refill threshold" value={`${tenant.poll_pool_refill_threshold_percent}% used`} />
          <DetailRow label="Gemini model" value={tenant.gemini_model} />
          <DetailRow label="WhatsApp connector" value={connector?.provider?.toUpperCase() || "Not configured"} />
          <DetailRow label={isWaha ? "WAHA base URL" : "GreenAPI URL"} value={String(isWaha ? connectorConfig.base_url || "" : connectorConfig.api_url || "")} />
        </section>

        <aside className="surface side-surface">
          <div className="section-header">
            <div>
              <p className="section-kicker">Readiness</p>
              <h3>Integration status</h3>
            </div>
          </div>
          <div className="stack">
            {readiness.map((item) => (
              <div className="result-row" key={item.label}>
                <span>{item.label}</span>
                <span className={item.ready ? "pill success" : "pill"}>{item.ready ? "Configured" : "Missing"}</span>
              </div>
            ))}
          </div>
          <div className="section-header" style={{ marginTop: "1.25rem" }}>
            <div>
              <p className="section-kicker">Activity</p>
              <h3>Recent provider events</h3>
            </div>
          </div>
          <div className="stack">
            {activityRows.map((item) => (
              <div className="result-row" key={item.label}>
                <span>{item.label}</span>
                <span>{item.value}</span>
              </div>
            ))}
          </div>
          <div className="section-header" style={{ marginTop: "1.25rem" }}>
            <div>
              <p className="section-kicker">Pilot readiness</p>
              <h3>Launch checklist</h3>
            </div>
          </div>
          {pilotReadinessLoading ? (
            <EmptyState title="Loading pilot readiness" body="Checking workspace setup, content, rules, and platform readiness." />
          ) : pilotReadinessError ? (
            <div className="alert error">{pilotReadinessError}</div>
          ) : (
            <div className="stack">
              {pilotReadiness?.items.map((item) => (
                <div className="result-row" key={item.label}>
                  <div>
                    <strong>{item.label}</strong>
                    <p className="subtle">{item.detail}</p>
                  </div>
                  <span className={item.ready ? "pill success" : "pill"}>{item.ready ? "Ready" : "Pending"}</span>
                </div>
              ))}
              {pilotReadiness && pilotReadiness.warnings.length > 0 && (
                <div className="subtle">{pilotReadiness.warnings.join(" · ")}</div>
              )}
              {pilotReadiness?.ok && <span className="pill success">Pilot ready</span>}
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}
