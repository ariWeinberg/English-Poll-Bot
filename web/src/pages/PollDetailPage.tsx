import React from "react";
import { ArrowLeft, Pencil, Trash2 } from "lucide-react";
import { EmptyState, StatBlock } from "../components/common";
import { describeIgnoredReason, describeVoteEvent, formatSnapshotSource, formatVoteContact, formatWhen, minutesLabel } from "../lib/format";
import type { Poll, PollCoverage, PollStats, VoteEvent, VoteStatus } from "../types";

export function PollDetailPage({
  poll,
  stats,
  coverage,
  voteStatus,
  events,
  onBack,
  onEdit,
  onDelete,
}: {
  poll: Poll | null;
  stats: PollStats | null;
  coverage: PollCoverage | null;
  voteStatus: VoteStatus[];
  events: VoteEvent[];
  onBack: () => void;
  onEdit: (poll: Poll) => void;
  onDelete: (poll: Poll) => void;
}) {
  if (!poll) {
    return <EmptyState title="Poll not found" body="The selected poll no longer exists." />;
  }

  return (
    <section className="detail-page">
      <button className="back-link" onClick={onBack}>
        <ArrowLeft size={16} /> Back to polls
      </button>
      <div className="detail-hero">
        <div>
          <p className="section-kicker">Poll #{poll.id}</p>
          <h2>{poll.question}</h2>
          <p className="hero-subtitle">{poll.chat_id}</p>
        </div>
        <div className="hero-actions">
          <button className="button button-primary" onClick={() => onEdit(poll)}>
            <Pencil size={16} /> Edit poll
          </button>
          <button className="button button-danger" onClick={() => onDelete(poll)}>
            <Trash2 size={16} /> Delete poll
          </button>
        </div>
      </div>

      <div className="detail-layout">
        <section className="surface">
          <div className="section-header">
            <div>
              <p className="section-kicker">Results</p>
              <h3>Answer distribution</h3>
            </div>
          </div>
          <div className="stack">
            {poll.options.map((option) => (
              <div className="result-row" key={option}>
                <div>
                  <strong>{option}</strong>
                  {option === poll.correct_option && <span className="pill success">Correct</span>}
                </div>
                <span>{stats?.counts[option] || 0} votes</span>
              </div>
            ))}
          </div>
          <div className="detail-summary">
            <StatBlock label="Total votes" value={stats?.total || 0} />
            <StatBlock label="Correct rate" value={`${stats?.correct_rate.toFixed(1) || "0.0"}%`} />
            <StatBlock label="Status" value={poll.status} />
            <StatBlock label="Review state" value={poll.review_status} />
            <StatBlock label="Vote changes" value={minutesLabel(poll.change_window_seconds)} />
            <StatBlock label="Poll lock" value={poll.manual_lock ? "Locked" : "Open"} />
            <StatBlock label="Auto-lock" value={minutesLabel(poll.auto_lock_seconds)} />
          </div>
          <div className="prose-block subtle">{poll.explanation || "No explanation provided."}</div>
          <div className="prose-block subtle">{poll.review_notes || "No review notes recorded."}</div>
          <div className="section-header">
            <div>
              <p className="section-kicker">Participation Coverage</p>
              <h3>Assigned vs responded</h3>
            </div>
          </div>
          <div className="detail-summary">
            <StatBlock label="Assigned" value={coverage?.assigned_count ?? 0} />
            <StatBlock label="Responded" value={coverage?.responded_count ?? 0} />
            <StatBlock label="Missed" value={coverage?.missed_count ?? 0} />
            <StatBlock label="Response rate" value={`${coverage?.response_rate.toFixed(1) ?? "0.0"}%`} />
          </div>
          <div className="prose-block subtle">
            {coverage?.coverage_available
              ? `Snapshot ${formatSnapshotSource(coverage?.recipient_snapshot_source)} · synced ${formatWhen(coverage?.recipient_snapshot_synced_at)}`
              : "Coverage was unavailable when this poll was sent, so non-responders could not be determined."}
          </div>
          <div className="status-table-wrap">
            {coverage && coverage.items.length > 0 ? (
              <table className="status-table">
                <thead>
                  <tr>
                    <th>Non-responder</th>
                    <th>Assigned at</th>
                  </tr>
                </thead>
                <tbody>
                  {coverage.items.map((item) => (
                    <tr key={item.voter_wid}>
                      <td>
                        <strong>{item.display_name}</strong>
                        <div className="meta-inline">{item.phone_number} · {item.voter_wid}</div>
                      </td>
                      <td>{formatWhen(item.assigned_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <EmptyState title="No missed responses" body={coverage?.coverage_available ? "Everyone assigned to this poll has responded." : "Coverage tracking was unavailable for this poll."} />
            )}
          </div>
        </section>

        <aside className="surface side-surface">
          <div className="section-header">
            <div>
              <p className="section-kicker">Current Vote Status</p>
              <h3>By contact</h3>
            </div>
          </div>
          <div className="status-table-wrap">
            {voteStatus.length > 0 ? (
              <table className="status-table">
                <thead>
                  <tr>
                    <th>Contact</th>
                    <th>Counted vote</th>
                    <th>First vote</th>
                    <th>Last accepted</th>
                    <th>Ignored latest</th>
                  </tr>
                </thead>
                <tbody>
                  {voteStatus.map((item) => (
                    <tr key={item.voter_wid}>
                      <td>{formatVoteContact(item)}</td>
                      <td>{item.counted_option_name || "Not counted"}</td>
                      <td>{item.first_accepted_at || "—"}</td>
                      <td>{item.updated_at || "—"}</td>
                      <td>{item.latest_ignored_option_name ? `${item.latest_ignored_option_name} (${describeIgnoredReason(item.latest_ignored_reason)})` : "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <EmptyState title="No vote status yet" body="Accepted and ignored vote attempts will appear here by contact." />
            )}
          </div>
          <div className="section-header">
            <div>
              <p className="section-kicker">Poll Events</p>
              <h3>Vote timeline</h3>
            </div>
          </div>
          <div className="stack">
            {events.map((event) => (
              <article className="event-row" key={event.id}>
                <div className="event-row-top">
                  <span className="pill">{formatVoteContact(event)}</span>
                  <span className="meta-inline">{event.recorded_at}</span>
                </div>
                <strong>{describeVoteEvent(event)}</strong>
              </article>
            ))}
            {events.length === 0 && <EmptyState title="No poll events yet" body="Vote changes will appear here as GreenAPI updates arrive." />}
          </div>
        </aside>
      </div>
    </section>
  );
}
