import React from "react";
import { ExternalLink } from "lucide-react";

function DocItem({ title, body }: { title: string; body: string }) {
  return (
    <article className="doc-item">
      <strong>{title}</strong>
      <p>{body}</p>
    </article>
  );
}

export function DocPage({ onOpenSwagger }: { onOpenSwagger: () => void }) {
  const qualityGates = [
    "python -m compileall app tests",
    "ruff check app tests",
    "ruff format --check app tests",
    "pytest",
    "cd web && npm run typecheck",
    "cd web && npm run build",
    "docker compose config --quiet",
  ];
  const loggingVars = ["LOG_LEVEL", "LOG_FORMAT", "LOG_FILE", "LOG_HUMAN_FILE", "LOG_REQUEST_BODY_ENABLED"];

  return (
    <section className="detail-page">
      <div className="detail-hero">
        <div>
          <p className="section-kicker">Operations Docs</p>
          <h2>Runbook and API access</h2>
          <p className="hero-subtitle">Authenticated local guidance for deployment checks, diagnostics, webhooks, and scheduler behavior.</p>
        </div>
        <div className="hero-actions">
          <button className="button button-primary" onClick={onOpenSwagger}>
            <ExternalLink size={16} /> Open Swagger
          </button>
        </div>
      </div>

      <div className="doc-grid">
        <section className="surface">
          <div className="section-header">
            <div>
              <p className="section-kicker">Daily Operations</p>
              <h3>Deployment checklist</h3>
            </div>
          </div>
          <div className="doc-list">
            <DocItem title="Configuration" body="Set tenant credentials in Workspace Settings and keep production secrets out of source." />
            <DocItem title="Scheduler" body="Tenant and text toggles must both be enabled before timed polls or summaries are sent." />
            <DocItem title="Webhooks" body="GreenAPI callbacks post to /webhooks/greenapi/{tenant_id}; every request is stored in the Webhook Inbox with accepted, ignored, or error status." />
            <DocItem title="API docs" body="Swagger and OpenAPI are disabled publicly. Use this page to mint a short-lived docs session." />
          </div>
        </section>

        <aside className="surface side-surface">
          <div className="section-header">
            <div>
              <p className="section-kicker">Logging</p>
              <h3>Local diagnostics</h3>
            </div>
          </div>
          <p className="subtle">JSON logs and human-readable logs are written locally by default with request IDs and secret redaction.</p>
          <div className="option-badges">
            {loggingVars.map((item) => (
              <span className="pill" key={item}>
                {item}
              </span>
            ))}
          </div>
        </aside>
      </div>

      <section className="surface">
        <div className="section-header">
          <div>
            <p className="section-kicker">Quality Gates</p>
            <h3>Before release</h3>
          </div>
        </div>
        <div className="command-list">
          {qualityGates.map((command) => (
            <code key={command}>{command}</code>
          ))}
        </div>
      </section>
    </section>
  );
}
