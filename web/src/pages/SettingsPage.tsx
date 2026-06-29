import React from "react";
import { FilePenLine } from "lucide-react";
import { DetailRow } from "../components/common";
import type { Tenant } from "../types";

export function SettingsPage({ tenant, onEdit }: { tenant: Tenant; onEdit: () => void }) {
  const connector = tenant.whatsapp_connector;
  const connectorConfig = connector?.config || {};
  const readiness = [
    { label: "Connector provider", ready: Boolean(connector?.provider) },
    { label: connector?.provider === "waha" ? "WAHA base URL" : "GreenAPI URL", ready: Boolean(connectorConfig.api_url || connectorConfig.base_url) },
    { label: connector?.provider === "waha" ? "WAHA session" : "GreenAPI instance", ready: Boolean(connectorConfig.session || connectorConfig.id_instance) },
    { label: connector?.provider === "waha" ? "WAHA API key" : "GreenAPI token", ready: connector?.provider === "waha" ? true : Boolean(connectorConfig.api_token_instance) },
    { label: "Gemini API key", ready: Boolean(tenant.gemini_api_key) },
  ];

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
          <DetailRow label="Pool threshold" value={`${tenant.poll_pool_threshold_percent}% used`} />
          <DetailRow label="Gemini model" value={tenant.gemini_model} />
          <DetailRow label="WhatsApp connector" value={connector?.provider?.toUpperCase() || "Not configured"} />
          <DetailRow label={connector?.provider === "waha" ? "WAHA base URL" : "GreenAPI URL"} value={String(connectorConfig.base_url || connectorConfig.api_url || "")} />
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
        </aside>
      </div>
    </section>
  );
}
