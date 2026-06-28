import React, { useEffect, useState } from "react";
import { api } from "../lib/api";
import { formatActivity, learnerQueryString } from "../lib/format";
import type { LearnerFilters, LearnerSummary, Page, Tenant, Text } from "../types";
import { EmptyState, TextInput } from "../components/common";

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
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setPage(1);
  }, [filters.search, filters.textId, filters.dateFrom, filters.dateTo, filters.sortBy, filters.sortDir]);

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

  return (
    <section className="detail-page">
      <div className="detail-hero">
        <div>
          <p className="section-kicker">Learner Progress Dashboard</p>
          <h2>Leaderboard</h2>
          <p className="hero-subtitle">Track participation, answer accuracy, ignored changes, and missed polls by contact.</p>
        </div>
      </div>
      <div className="toolbar learner-toolbar">
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
            <option value="total_counted_votes:desc">Total answers</option>
            <option value="correct_rate:desc">Accuracy</option>
            <option value="response_rate:desc">Response rate</option>
            <option value="missed_polls_count:desc">Most missed polls</option>
            <option value="assigned_polls_count:desc">Most assigned polls</option>
            <option value="correct_rate:asc">Lowest accuracy</option>
          </select>
        </label>
      </div>
      <section className="surface">
        <div className="section-header">
          <div>
            <p className="section-kicker">Leaderboard</p>
            <h3>Participation and accuracy</h3>
          </div>
          <span className="pill">{data?.total ?? 0} learners</span>
        </div>
        {error && <div className="alert error">{error}</div>}
        <div className="status-table-wrap">
          {loading ? (
            <EmptyState title="Loading learners" body="Aggregating vote history for this workspace." />
          ) : data && data.items.length > 0 ? (
            <table className="status-table learner-table">
              <thead>
                <tr>
                  <th>Learner</th>
                  <th>Total answers</th>
                  <th>Polls seen</th>
                  <th>Assigned</th>
                  <th>Missed</th>
                  <th>Response rate</th>
                  <th>Correct</th>
                  <th>Accuracy</th>
                  <th>Accepted changes</th>
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
                        <span className="meta-inline">{item.phone_number} · {item.voter_wid}</span>
                      </button>
                    </td>
                    <td>{item.total_counted_votes}</td>
                    <td>{item.total_polls_seen}</td>
                    <td>{item.assigned_polls_count}</td>
                    <td>{item.missed_polls_count}</td>
                    <td>{item.response_rate.toFixed(1)}%</td>
                    <td>{item.correct_count}/{item.incorrect_count}</td>
                    <td>{item.correct_rate.toFixed(1)}%</td>
                    <td>{item.accepted_changes_count}</td>
                    <td>{item.ignored_changes_count}</td>
                    <td>{formatActivity(item.latest_activity)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState title="No learners yet" body="Learners will appear here after recorded poll votes arrive." />
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
