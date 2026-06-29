import React, { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Clock3, Users } from "lucide-react";

import { EmptyState, TextInput } from "../components/common";
import { api } from "../lib/api";
import { dateRangeForPreset, matchingRangePreset, type AnalyticsRangePreset } from "../lib/analytics";
import { formatActivity, formatPercent, learnerQueryString } from "../lib/format";
import type { LearnerFilters, LearnerSummary, LearnerSummaryResponse, Page, Tenant, Text } from "../types";

const segmentMeta = {
  all: { label: "All learners", tone: "neutral", description: "Everyone in the current filter scope." },
  needs_attention: { label: "Needs attention", tone: "danger", description: "Missed polls or response rate below 50%." },
  inactive: { label: "Inactive", tone: "warning", description: "Assigned polls but no responses yet." },
  engaged: { label: "Engaged", tone: "success", description: "High response rate with no misses." },
} as const;

export function LearnersPage({
  tenant,
  texts,
  filters,
  onFiltersChange,
  onOpenLearner,
}: {
  tenant: Tenant;
  texts: Text[];
  filters: LearnerFilters;
  onFiltersChange: React.Dispatch<React.SetStateAction<LearnerFilters>>;
  onOpenLearner: (learner: LearnerSummary) => void;
}) {
  const [page, setPage] = useState(1);
  const [data, setData] = useState<Page<LearnerSummary> | null>(null);
  const [summary, setSummary] = useState<LearnerSummaryResponse | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [summaryLoading, setSummaryLoading] = useState(true);
  const activePreset = matchingRangePreset(filters.dateFrom, filters.dateTo);

  useEffect(() => {
    setPage(1);
  }, [filters.search, filters.textId, filters.dateFrom, filters.dateTo, filters.segment, filters.sortBy, filters.sortDir]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    api<Page<LearnerSummary>>(`/learners?${learnerQueryString(tenant.id, filters, { page, page_size: 25 })}`)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load learners");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenant.id, filters, page]);

  useEffect(() => {
    let cancelled = false;
    setSummaryLoading(true);
    api<LearnerSummaryResponse>(`/learners/summary?${learnerQueryString(tenant.id, filters)}`)
      .then((result) => {
        if (!cancelled) setSummary(result);
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Failed to load learner summary");
      })
      .finally(() => {
        if (!cancelled) setSummaryLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [tenant.id, filters.dateFrom, filters.dateTo, filters.textId]);

  function applyPreset(preset: AnalyticsRangePreset) {
    const range = dateRangeForPreset(preset);
    onFiltersChange((current) => ({ ...current, ...range }));
  }

  const tableLabel = segmentMeta[filters.segment].label;

  return (
    <section className="detail-page">
      <div className="detail-hero">
        <div>
          <p className="section-kicker">Learner Intervention Dashboard</p>
          <h2>Learners</h2>
          <p className="hero-subtitle">Prioritize who needs follow-up first, then drill into the detailed response history below.</p>
        </div>
      </div>

      <div className="toolbar learner-toolbar">
        <div className="preset-group">
          {(["7d", "30d", "all"] as const).map((preset) => (
            <button
              key={preset}
              className={activePreset === preset ? "button button-secondary" : "button button-ghost"}
              onClick={() => applyPreset(preset)}
            >
              {preset === "all" ? "All time" : preset}
            </button>
          ))}
        </div>
        <TextInput
          label="Search learners"
          value={filters.search}
          onChange={(value) => onFiltersChange((current) => ({ ...current, search: value }))}
          placeholder="Name, phone, or WhatsApp ID"
        />
        <label>
          Text
          <select value={filters.textId} onChange={(event) => onFiltersChange((current) => ({ ...current, textId: event.target.value }))}>
            <option value="">All texts</option>
            {texts.map((text) => (
              <option key={text.id} value={text.id}>
                {text.title}
              </option>
            ))}
          </select>
        </label>
        <TextInput label="From" type="date" value={filters.dateFrom} onChange={(value) => onFiltersChange((current) => ({ ...current, dateFrom: value }))} />
        <TextInput label="To" type="date" value={filters.dateTo} onChange={(value) => onFiltersChange((current) => ({ ...current, dateTo: value }))} />
        <label>
          Sort
          <select
            value={`${filters.sortBy}:${filters.sortDir}`}
            onChange={(event) => {
              const [sortBy, sortDir] = event.target.value.split(":") as [LearnerFilters["sortBy"], LearnerFilters["sortDir"]];
              onFiltersChange((current) => ({ ...current, sortBy, sortDir }));
            }}
          >
            <option value="latest_activity:desc">Latest activity</option>
            <option value="response_rate:asc">Lowest response rate</option>
            <option value="missed_polls_count:desc">Most missed polls</option>
            <option value="total_counted_votes:desc">Most answers</option>
            <option value="correct_rate:desc">Highest accuracy</option>
            <option value="correct_rate:asc">Lowest accuracy</option>
          </select>
        </label>
      </div>

      {error && <div className="alert error">{error}</div>}

      <section className="metric-grid learner-metric-grid">
        <MetricCard label="Learners in scope" value={summary?.learners_total ?? 0} detail="Any assigned or responding learner in this range" icon={<Users size={18} />} />
        <MetricCard label="Assigned polls" value={summary?.assigned_polls_total ?? 0} detail="Coverage opportunities sent to learners" icon={<Clock3 size={18} />} />
        <MetricCard label="Missed polls" value={summary?.missed_polls_total ?? 0} detail="Unanswered assigned polls" icon={<AlertTriangle size={18} />} />
        <MetricCard label="Response rate" value={formatPercent(summary?.response_rate ?? 0)} detail="Responses divided by assigned polls" icon={<CheckCircle2 size={18} />} />
        <MetricCard label="Accuracy" value={formatPercent(summary?.correct_rate ?? 0)} detail="Correct answers across counted votes" icon={<CheckCircle2 size={18} />} />
        <MetricCard label="Ignored changes" value={summary?.ignored_changes_total ?? 0} detail="Late or blocked answer changes" icon={<AlertTriangle size={18} />} />
      </section>

      <div className="segment-grid">
        <button
          className={filters.segment === "needs_attention" ? "surface segment-card active danger" : "surface segment-card danger"}
          onClick={() => onFiltersChange((current) => ({ ...current, segment: "needs_attention" }))}
        >
          <p className="section-kicker">Needs attention</p>
          <strong>{summary?.needs_attention_count ?? 0}</strong>
          <p>{segmentMeta.needs_attention.description}</p>
        </button>
        <button
          className={filters.segment === "inactive" ? "surface segment-card active warning" : "surface segment-card warning"}
          onClick={() => onFiltersChange((current) => ({ ...current, segment: "inactive" }))}
        >
          <p className="section-kicker">Inactive</p>
          <strong>{summary?.inactive_count ?? 0}</strong>
          <p>{segmentMeta.inactive.description}</p>
        </button>
        <button
          className={filters.segment === "engaged" ? "surface segment-card active success" : "surface segment-card success"}
          onClick={() => onFiltersChange((current) => ({ ...current, segment: "engaged" }))}
        >
          <p className="section-kicker">Engaged</p>
          <strong>{summary?.engaged_count ?? 0}</strong>
          <p>{segmentMeta.engaged.description}</p>
        </button>
      </div>

      <div className="content-grid">
        <section className="surface">
          <div className="section-header">
            <div>
              <p className="section-kicker">Risk Strips</p>
              <h3>Top missed learners</h3>
            </div>
          </div>
          {summaryLoading ? (
            <EmptyState title="Loading ranked learners" body="Building intervention slices for the selected range." />
          ) : (
            <RankedLearnerList
              items={summary?.top_missed ?? []}
              emptyTitle="No missed learners"
              emptyBody="No learner missed an assigned poll in the current filter range."
              valueFor={(learner) => `${learner.missed_polls_count} missed`}
              metaFor={(learner) => `${formatPercent(learner.response_rate)} response`}
              onOpenLearner={onOpenLearner}
            />
          )}
        </section>

        <section className="surface">
          <div className="section-header">
            <div>
              <p className="section-kicker">Risk Strips</p>
              <h3>Lowest response learners</h3>
            </div>
          </div>
          {summaryLoading ? (
            <EmptyState title="Loading ranked learners" body="Scoring response risk for this workspace." />
          ) : (
            <RankedLearnerList
              items={summary?.lowest_response ?? []}
              emptyTitle="No low-response learners"
              emptyBody="Every assigned learner has stayed responsive in the current filter range."
              valueFor={(learner) => formatPercent(learner.response_rate)}
              metaFor={(learner) => `${learner.assigned_polls_count} assigned · ${learner.missed_polls_count} missed`}
              onOpenLearner={onOpenLearner}
            />
          )}
        </section>
      </div>

      <section className="surface">
        <div className="section-header">
          <div>
            <p className="section-kicker">Detailed Table</p>
            <h3>{tableLabel}</h3>
          </div>
          <div className="card-actions">
            <span className="pill">{data?.total ?? 0} learners</span>
            {filters.segment !== "all" && (
              <button className="button button-ghost" onClick={() => onFiltersChange((current) => ({ ...current, segment: "all" }))}>
                Show all
              </button>
            )}
          </div>
        </div>
        <div className="status-table-wrap">
          {loading ? (
            <EmptyState title="Loading learners" body="Aggregating vote history for this workspace." />
          ) : data && data.items.length > 0 ? (
            <table className="status-table learner-table">
              <thead>
                <tr>
                  <th>Learner</th>
                  <th>Assigned</th>
                  <th>Responded</th>
                  <th>Missed</th>
                  <th>Response rate</th>
                  <th>Total answers</th>
                  <th>Accuracy</th>
                  <th>Ignored changes</th>
                  <th>Latest activity</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((item) => (
                  <tr key={item.voter_wid}>
                    <td>
                      <button className="table-button" onClick={() => onOpenLearner(item)}>
                        <strong>{item.display_name}</strong>
                        <span className="meta-inline">
                          {item.phone_number} · {item.voter_wid}
                        </span>
                      </button>
                    </td>
                    <td>{item.assigned_polls_count}</td>
                    <td>{item.responded_polls_count}</td>
                    <td>{item.missed_polls_count}</td>
                    <td>{formatPercent(item.response_rate)}</td>
                    <td>{item.total_counted_votes}</td>
                    <td>{formatPercent(item.correct_rate)}</td>
                    <td>{item.ignored_changes_count}</td>
                    <td>{formatActivity(item.latest_activity)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState title="No learners in this segment" body="Try widening the date range or switching back to all learners." />
          )}
        </div>
        {data && data.total > 0 && (
          <div className="card-actions">
            <button className="button button-ghost" disabled={page <= 1} onClick={() => setPage((current) => Math.max(1, current - 1))}>
              Previous
            </button>
            <span className="pill">Page {data.page}</span>
            <button className="button button-ghost" disabled={!data.has_next} onClick={() => setPage((current) => current + 1)}>
              Next
            </button>
          </div>
        )}
      </section>
    </section>
  );
}

function MetricCard({ label, value, detail, icon }: { label: string; value: string | number; detail: string; icon: React.ReactNode }) {
  return (
    <article className="metric-card">
      <div className="metric-icon">{icon}</div>
      <span>{label}</span>
      <strong>{value}</strong>
      <p>{detail}</p>
    </article>
  );
}

function RankedLearnerList({
  items,
  emptyTitle,
  emptyBody,
  valueFor,
  metaFor,
  onOpenLearner,
}: {
  items: LearnerSummary[];
  emptyTitle: string;
  emptyBody: string;
  valueFor: (learner: LearnerSummary) => string;
  metaFor: (learner: LearnerSummary) => string;
  onOpenLearner: (learner: LearnerSummary) => void;
}) {
  if (items.length === 0) return <EmptyState title={emptyTitle} body={emptyBody} />;
  const maxAssigned = Math.max(...items.map((item) => Math.max(item.assigned_polls_count, 1)));

  return (
    <div className="stack">
      {items.map((learner) => (
        <button className="ranked-strip" key={learner.voter_wid} onClick={() => onOpenLearner(learner)}>
          <div className="ranked-strip-copy">
            <strong>{learner.display_name}</strong>
            <span className="meta-inline">{learner.phone_number}</span>
          </div>
          <div className="ranked-strip-bar">
            <div className="mini-bar-track">
              <div className="mini-bar-fill" style={{ width: `${Math.max((learner.assigned_polls_count / maxAssigned) * 100, 16)}%` }} />
            </div>
          </div>
          <div className="ranked-strip-metrics">
            <strong>{valueFor(learner)}</strong>
            <span className="meta-inline">{metaFor(learner)}</span>
          </div>
        </button>
      ))}
    </div>
  );
}
