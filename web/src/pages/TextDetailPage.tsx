import React from "react";
import { ArrowLeft, Pencil, Play, Power, RefreshCw, Send, Trash2 } from "lucide-react";
import { DetailRow, EmptyState, StatBlock } from "../components/common";
import { describeRule, formatWhen, scheduleSummary } from "../lib/format";
import type { Poll, PollPool, Text, TextRoster } from "../types";

export function TextDetailPage({
  text,
  pool,
  roster,
  onBack,
  onEdit,
  onPreview,
  onSendPoll,
  onToggleEnabled,
  onSyncRoster,
  onToggleRosterExclusion,
  onRefillPool,
  onMovePoolPoll,
  onDelete,
  onDeleteQueuedPoll,
}: {
  text: Text | null;
  pool: PollPool | null;
  roster: TextRoster | null;
  onBack: () => void;
  onEdit: (text: Text) => void;
  onPreview: (textId: number) => void;
  onSendPoll: (textId: number) => void;
  onToggleEnabled: (text: Text) => void;
  onSyncRoster: (textId: number) => void;
  onToggleRosterExclusion: (textId: number, voterWid: string, excluded: boolean) => void;
  onRefillPool: (textId: number) => void;
  onMovePoolPoll: (pollId: number, poolRank: number) => void;
  onDelete: (text: Text) => void;
  onDeleteQueuedPoll: (poll: Poll) => void;
}) {
  if (!text) {
    return <EmptyState title="Text not found" body="The selected text no longer exists." />;
  }

  return (
    <section className="detail-page">
      <button className="back-link" onClick={onBack}>
        <ArrowLeft size={16} /> Back to texts
      </button>
      <div className="detail-hero">
        <div>
          <p className="section-kicker">Text #{text.id}</p>
          <h2>{text.title}</h2>
          <p className="hero-subtitle">{text.chat_id || "No chat ID configured yet."}</p>
        </div>
        <div className="hero-actions">
          <button className="button button-secondary" onClick={() => onPreview(text.id)}>
            <Play size={16} /> Preview next poll
          </button>
          <button className="button button-secondary" onClick={() => onSendPoll(text.id)}>
            <Send size={16} /> Send poll
          </button>
          <button className={text.enabled ? "button button-ghost" : "button button-secondary"} onClick={() => onToggleEnabled(text)}>
            <Power size={16} /> {text.enabled ? "Disable text" : "Enable text"}
          </button>
          <button className="button button-primary" onClick={() => onEdit(text)}>
            <Pencil size={16} /> Edit text
          </button>
        </div>
      </div>

      <div className="detail-layout">
        <section className="surface">
          <div className="section-header">
            <div>
              <p className="section-kicker">Content</p>
              <h3>Body</h3>
            </div>
          </div>
          <div className="prose-block">{text.body}</div>
        </section>

        <aside className="surface side-surface">
          <div className="section-header">
            <div>
              <p className="section-kicker">Delivery</p>
              <h3>Schedule</h3>
            </div>
          </div>
          <DetailRow label="Delivery rules" value={scheduleSummary(text)} />
          <div className="stack">
            {text.schedule_rules.length > 0 ? text.schedule_rules.map((rule, index) => <div key={rule.id || `${rule.delivery_type}-${index}`}>{describeRule(rule)}</div>) : <div>Manual only</div>}
          </div>
          <DetailRow
            label="Pool threshold"
            value={text.poll_pool_threshold_percent == null ? `Inherited ${text.tenant_poll_pool_threshold_percent ?? 80}% used` : `${text.poll_pool_threshold_percent}% used`}
          />
          <DetailRow label="Pool target size" value={String(text.tenant_poll_pool_target_size ?? 10)} />
          <DetailRow label="Refill batch size" value={String(text.tenant_poll_pool_refill_batch_size ?? 5)} />
          <DetailRow label="Refill threshold" value={`${text.tenant_poll_pool_refill_threshold_percent ?? 80}% used`} />
          <DetailRow label="Attachment" value={text.attachment_name || "None"} />
          <DetailRow label="Status" value={text.enabled ? "Enabled" : "Disabled"} />
          <button className="button button-danger full-width" onClick={() => onDelete(text)}>
            <Trash2 size={16} /> Delete text
          </button>
        </aside>
      </div>

      <section className="surface">
        <div className="section-header">
          <div>
            <p className="section-kicker">Group Roster</p>
            <h3>Coverage membership</h3>
          </div>
          <button className="button button-secondary" onClick={() => onSyncRoster(text.id)}>
            <RefreshCw size={16} /> Sync contacts
          </button>
        </div>
        <div className="detail-summary">
          <StatBlock label="Active participants" value={roster?.active_count ?? 0} />
          <StatBlock label="Excluded" value={roster?.excluded_count ?? 0} />
          <StatBlock label="Last sync" value={formatWhen(roster?.last_synced_at)} />
        </div>
        <div className="status-table-wrap">
          {roster && roster.items.length > 0 ? (
            <table className="status-table">
              <thead>
                <tr>
                  <th>Learner</th>
                  <th>Active in chat</th>
                  <th>Coverage</th>
                  <th>Last sync</th>
                </tr>
              </thead>
              <tbody>
                {roster.items.map((item) => (
                  <tr key={item.voter_wid}>
                    <td>
                      <strong>{item.display_name}</strong>
                      <div className="meta-inline">{item.phone_number} · {item.voter_wid}</div>
                    </td>
                    <td>{item.is_active_in_chat ? "Active" : "Inactive"}</td>
                    <td>
                      <button
                        className={item.excluded_from_coverage ? "button button-ghost" : "button button-secondary"}
                        onClick={() => onToggleRosterExclusion(text.id, item.voter_wid, !item.excluded_from_coverage)}
                      >
                        {item.excluded_from_coverage ? "Excluded" : "Included"}
                      </button>
                    </td>
                    <td>{formatWhen(item.last_synced_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <EmptyState title="No roster synced yet" body="Sync the WhatsApp group participants to track missed responses for this text." />
          )}
        </div>
      </section>

      <section className="surface">
        <div className="section-header">
          <div>
            <p className="section-kicker">Poll Pool</p>
            <h3>Queued polls</h3>
          </div>
          <button className="button button-secondary" onClick={() => onRefillPool(text.id)}>
            <RefreshCw size={16} /> Refill pool
          </button>
        </div>
        <div className="detail-summary">
          <StatBlock label="Queued" value={pool?.queued_count ?? 0} />
          <StatBlock label="Target size" value={pool?.target_size ?? 10} />
          <StatBlock label="Threshold" value={`${pool?.effective_threshold_percent ?? text.tenant_poll_pool_threshold_percent ?? 80}% used`} />
          <StatBlock label="Refill below" value={pool?.refill_when_below ?? 2} />
        </div>
        {pool?.next_poll && (
          <div className="prose-block subtle">
            <strong>Next queued poll:</strong> {pool.next_poll.question}
          </div>
        )}
        <div className="stack">
          {pool?.items.map((poll, index) => (
            <article className="event-row" key={poll.id}>
              <div className="event-row-top">
                <span className="pill">Rank {poll.pool_rank}</span>
                <span className="meta-inline">Queued draft</span>
              </div>
              <strong>{poll.question}</strong>
              <p>{poll.options.join(" · ")}</p>
              <div className="card-actions">
                <button className="button button-ghost" onClick={() => onMovePoolPoll(poll.id, Math.max(1, (poll.pool_rank || index + 1) - 1))} disabled={index === 0}>
                  Up
                </button>
                <button className="button button-ghost" onClick={() => onMovePoolPoll(poll.id, (poll.pool_rank || index + 1) + 1)} disabled={index === pool.items.length - 1}>
                  Down
                </button>
                <button className="button button-danger" onClick={() => onDeleteQueuedPoll(poll)}>
                  <Trash2 size={16} /> Delete
                </button>
              </div>
            </article>
          ))}
          {(!pool || pool.items.length === 0) && <EmptyState title="No queued polls" body="Preview or refill to generate the next batch for this text." />}
        </div>
      </section>
    </section>
  );
}
