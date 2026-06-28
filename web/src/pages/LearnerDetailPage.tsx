import React, { useEffect, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { EmptyState, StatBlock } from "../components/common";
import { api } from "../lib/api";
import { describeIgnoredReason, formatActivity, formatSnapshotSource, formatWhen, learnerQueryString } from "../lib/format";
import type { LearnerDetail, LearnerFilters, Tenant, Text } from "../types";

export function LearnerDetailPage({
  tenant,
  texts,
  voterWid,
  filters,
  onBack,
}: {
  tenant: Tenant;
  texts: Text[];
  voterWid: string;
  filters: LearnerFilters;
  onBack: () => void;
}) {
  const [detail, setDetail] = useState<LearnerDetail | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const textTitle = texts.find((text) => String(text.id) === filters.textId)?.title;

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    api<LearnerDetail>(`/learners/${encodeURIComponent(voterWid)}?${learnerQueryString(tenant.id, filters, { history_limit: 25 })}`)
      .then((result) => {
        if (!cancelled) setDetail(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load learner detail");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenant.id, voterWid, filters]);

  if (loading) {
    return <EmptyState title="Loading learner detail" body="Fetching recent answer history and aggregate stats." />;
  }

  if (error) {
    return <div className="alert error">{error}</div>;
  }

  if (!detail) {
    return <EmptyState title="Learner not found" body="No recorded vote history matched this learner." />;
  }

  return (
    <section className="detail-page">
      <button className="back-link" onClick={onBack}>
        <ArrowLeft size={16} /> Back to learners
      </button>
      <div className="detail-hero">
        <div>
          <p className="section-kicker">Learner Detail</p>
          <h2>{detail.learner.display_name}</h2>
          <p className="hero-subtitle">{detail.learner.phone_number} · {detail.learner.voter_wid}</p>
        </div>
        <div className="option-badges">
          {textTitle && <span className="pill">Text: {textTitle}</span>}
          {filters.dateFrom && <span className="pill">From {filters.dateFrom}</span>}
          {filters.dateTo && <span className="pill">To {filters.dateTo}</span>}
        </div>
      </div>
      <section className="surface">
        <div className="detail-summary">
          <StatBlock label="Total answers" value={detail.learner.total_counted_votes} />
          <StatBlock label="Polls seen" value={detail.learner.total_polls_seen} />
          <StatBlock label="Assigned polls" value={detail.learner.assigned_polls_count} />
          <StatBlock label="Missed polls" value={detail.learner.missed_polls_count} />
          <StatBlock label="Response rate" value={`${detail.learner.response_rate.toFixed(1)}%`} />
          <StatBlock label="Correct" value={detail.learner.correct_count} />
          <StatBlock label="Incorrect" value={detail.learner.incorrect_count} />
          <StatBlock label="Accuracy" value={`${detail.learner.correct_rate.toFixed(1)}%`} />
          <StatBlock label="Accepted changes" value={detail.learner.accepted_changes_count} />
          <StatBlock label="Ignored changes" value={detail.learner.ignored_changes_count} />
          <StatBlock label="First activity" value={formatActivity(detail.learner.first_activity)} />
          <StatBlock label="Latest activity" value={formatActivity(detail.learner.latest_activity)} />
        </div>
      </section>
      <section className="surface">
        <div className="section-header">
          <div>
            <p className="section-kicker">Recent Answer History</p>
            <h3>Per-poll timeline</h3>
          </div>
        </div>
        <div className="stack">
          {detail.history.map((item) => (
            <article className="event-row" key={item.id}>
              <div className="event-row-top">
                <span className="pill">{item.question}</span>
                <span className="meta-inline">{item.recorded_at}</span>
              </div>
              <strong>{item.selected_option_name || "Cleared vote"} · correct answer {item.correct_option}</strong>
              <p className="subtle">
                {item.accepted
                  ? item.event_type === "change"
                    ? `Accepted change from ${item.previous_option_name || "—"}`
                    : "Accepted answer"
                  : `Ignored change: ${describeIgnoredReason(item.ignored_reason)}`}
              </p>
            </article>
          ))}
          {detail.history.length === 0 && <EmptyState title="No history in this filter range" body="Try widening the date or text filters." />}
        </div>
      </section>
      <section className="surface">
        <div className="section-header">
          <div>
            <p className="section-kicker">Recent Missed Polls</p>
            <h3>Coverage gaps</h3>
          </div>
        </div>
        <div className="stack">
          {detail.missed_polls.map((item) => (
            <article className="event-row" key={`${item.poll_id}:${item.sent_at || "na"}`}>
              <div className="event-row-top">
                <span className="pill">{item.question}</span>
                <span className="meta-inline">{formatWhen(item.sent_at)}</span>
              </div>
              <strong>Poll #{item.poll_id}</strong>
              <p className="subtle">Snapshot {formatSnapshotSource(item.recipient_snapshot_source)} · synced {formatWhen(item.recipient_snapshot_synced_at)}</p>
            </article>
          ))}
          {detail.missed_polls.length === 0 && <EmptyState title="No missed polls in this filter range" body="This learner responded to every assigned poll in the current scope." />}
        </div>
      </section>
    </section>
  );
}
