import React, { FormEvent, useState } from "react";
import { Save } from "lucide-react";
import { Modal, TextInput } from "./common";
import { api } from "../lib/api";
import { blankPoll, blankScheduleRule, blankText, pollToForm, tenantToForm, textToForm } from "../lib/forms";
import { autoSummaryRuleFor, describeRule, WEEKDAY_OPTIONS } from "../lib/format";
import type {
  GeneratedQuestion,
  GroupChat,
  Poll,
  PollFormState,
  ScheduleRule,
  Tenant,
  TenantFormState,
  Text,
  TextFormState,
} from "../types";

export function TextModal({
  tenant,
  initialText,
  availableChats,
  availableRules,
  onClose,
  onSaved,
  onError,
}: {
  tenant: Tenant;
  initialText?: Text;
  availableChats: GroupChat[];
  availableRules: ScheduleRule[];
  onClose: () => void;
  onSaved: (message: string) => void;
  onError: (message: string) => void;
}) {
  const editing = Boolean(initialText);
  const [form, setForm] = useState<TextFormState>(initialText ? textToForm(initialText) : blankText(tenant.id));
  const [attachment, setAttachment] = useState<File | null>(null);
  const [draftRule, setDraftRule] = useState<ScheduleRule>(blankScheduleRule());
  const [editingRuleIndex, setEditingRuleIndex] = useState<number | null>(null);
  const [autoSummary, setAutoSummary] = useState(true);
  const [selectedRuleId, setSelectedRuleId] = useState("");
  const [submitError, setSubmitError] = useState("");

  const selectableChats = availableChats.filter((chat) => chat.policy !== "block");
  const assignedExistingRules = availableRules.filter((rule) => rule.id && form.assigned_rule_ids.includes(rule.id));

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitError("");
    if (!form.chat_id.trim()) {
      const message = "Select a WhatsApp group chat before saving the text.";
      setSubmitError(message);
      onError(message);
      return;
    }
    try {
      const payload = {
        ...form,
        assigned_rule_ids: form.assigned_rule_ids,
        new_rules: form.new_rules.map(({ id: _id, tenant_id: _tenantId, text_id: _textId, ...rule }) => rule),
      };
      if (editing && initialText) {
        await api<Text>(`/texts/${initialText.id}`, { method: "PATCH", body: JSON.stringify(payload) });
        onSaved("Text updated");
        return;
      }
      const data = new FormData();
      data.set("tenant_id", String(tenant.id));
      data.set("title", form.title);
      data.set("body", form.body);
      data.set("chat_id", form.chat_id);
      data.set("assigned_rule_ids_json", JSON.stringify(form.assigned_rule_ids));
      data.set("new_rules_json", JSON.stringify(payload.new_rules));
      if (form.poll_pool_threshold_percent != null) data.set("poll_pool_threshold_percent", String(form.poll_pool_threshold_percent));
      data.set("enabled", String(form.enabled));
      if (attachment) data.set("attachment", attachment);
      await api<Text>("/texts", { method: "POST", body: data });
      onSaved("Text created");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to save text";
      setSubmitError(message);
      onError(message);
    }
  }

  function saveRule() {
    const rule: ScheduleRule = {
      ...draftRule,
      id: undefined,
      weekdays: draftRule.rule_type === "weekday_time" ? draftRule.weekdays || [] : [],
      month_dates: draftRule.rule_type === "month_date_time" ? draftRule.month_dates || [] : [],
    };
    const nextRules = [...form.new_rules];
    if (editingRuleIndex == null) nextRules.push(rule);
    else nextRules[editingRuleIndex] = rule;
    if (autoSummary && rule.delivery_type === "poll" && editingRuleIndex == null) {
      nextRules.push(autoSummaryRuleFor(rule));
    }
    setForm({ ...form, new_rules: nextRules });
    setDraftRule(blankScheduleRule());
    setEditingRuleIndex(null);
    setAutoSummary(true);
  }

  function editRule(index: number) {
    setDraftRule({ ...form.new_rules[index] });
    setEditingRuleIndex(index);
    setAutoSummary(false);
  }

  function removeRule(index: number) {
    setForm({ ...form, new_rules: form.new_rules.filter((_, ruleIndex) => ruleIndex !== index) });
    if (editingRuleIndex === index) {
      setDraftRule(blankScheduleRule());
      setEditingRuleIndex(null);
    }
  }

  function assignExistingRule() {
    const ruleId = Number(selectedRuleId);
    if (!ruleId || form.assigned_rule_ids.includes(ruleId)) return;
    setForm({ ...form, assigned_rule_ids: [...form.assigned_rule_ids, ruleId] });
    setSelectedRuleId("");
  }

  return (
    <Modal title={editing ? "Edit Text" : "Create Text"} onClose={onClose}>
      <form className="modal-form" onSubmit={submit}>
        {submitError && <div className="alert error">{submitError}</div>}
        <TextInput label="Title" value={form.title} onChange={(value) => setForm({ ...form, title: value })} />
        <label>
          Body
          <textarea rows={8} value={form.body} onChange={(event) => setForm({ ...form, body: event.target.value })} />
        </label>
        <label>
          WhatsApp group chat
          <select value={form.chat_id} onChange={(event) => setForm({ ...form, chat_id: event.target.value })}>
            <option value="">{selectableChats.length > 0 ? "Select a group chat" : "No group chats loaded"}</option>
            {form.chat_id && !selectableChats.some((chat) => chat.chat_id === form.chat_id) && <option value={form.chat_id}>{form.chat_id}</option>}
            {selectableChats.map((chat) => (
              <option key={chat.chat_id} value={chat.chat_id}>
                {chat.name} · {chat.chat_id}
              </option>
            ))}
          </select>
        </label>
        {selectableChats.length === 0 && <div className="alert warning">Refresh groups from the Groups page after configuring your WhatsApp connector, then create texts from the dropdown instead of typing chat IDs manually.</div>}
        <div className="surface">
          <div className="section-header">
            <div>
              <p className="section-kicker">Schedule rules</p>
              <h3>{[...assignedExistingRules, ...form.new_rules].some((rule) => rule.delivery_type === "poll" && rule.enabled) ? "Rules configured" : "Manual only"}</h3>
            </div>
          </div>
          <div className="time-grid">
            <label>
              Assign existing rule
              <select value={selectedRuleId} onChange={(event) => setSelectedRuleId(event.target.value)}>
                <option value="">Select shared rule</option>
                {availableRules.filter((rule) => rule.id && !form.assigned_rule_ids.includes(rule.id)).map((rule) => (
                  <option key={rule.id} value={rule.id}>
                    {rule.name || describeRule(rule)}
                  </option>
                ))}
              </select>
            </label>
            <div className="modal-actions">
              <button className="button button-secondary" type="button" onClick={assignExistingRule}>
                Assign rule
              </button>
            </div>
          </div>
          <div className="stack">
            {assignedExistingRules.map((rule) => (
              <div className="result-row" key={rule.id}>
                <span>{describeRule(rule)}</span>
                <span>
                  <button className="button button-ghost" type="button" onClick={() => setForm({ ...form, assigned_rule_ids: form.assigned_rule_ids.filter((ruleId) => ruleId !== rule.id) })}>
                    Remove
                  </button>
                </span>
              </div>
            ))}
            {form.new_rules.map((rule, index) => (
              <div className="result-row" key={rule.id || `${rule.delivery_type}-${index}`}>
                <span>{describeRule(rule)}</span>
                <span>
                  <button className="button button-ghost" type="button" onClick={() => editRule(index)}>Edit</button>
                  <button className="button button-ghost" type="button" onClick={() => removeRule(index)}>Delete</button>
                </span>
              </div>
            ))}
            {assignedExistingRules.length === 0 && form.new_rules.length === 0 ? <div>No enabled poll rules yet. This text will stay manual-only.</div> : null}
          </div>
          <div className="time-grid">
            <label>
              Delivery type
              <select value={draftRule.delivery_type} onChange={(event) => setDraftRule({ ...draftRule, delivery_type: event.target.value as ScheduleRule["delivery_type"] })}>
                <option value="poll">Poll</option>
                <option value="summary">Summary</option>
              </select>
            </label>
            <label>
              Rule type
              <select value={draftRule.rule_type} onChange={(event) => setDraftRule({ ...draftRule, rule_type: event.target.value as ScheduleRule["rule_type"] })}>
                <option value="daily_time">Daily time</option>
                <option value="weekday_time">Weekday time</option>
                <option value="month_date_time">Month date time</option>
                <option value="random_window">Random window</option>
              </select>
            </label>
            {draftRule.rule_type === "random_window" ? (
              <>
                <TextInput label="Window start" value={draftRule.window_start || ""} onChange={(value) => setDraftRule({ ...draftRule, window_start: value })} />
                <TextInput label="Window end" value={draftRule.window_end || ""} onChange={(value) => setDraftRule({ ...draftRule, window_end: value })} />
              </>
            ) : (
              <TextInput label="Time" value={draftRule.time || ""} onChange={(value) => setDraftRule({ ...draftRule, time: value })} />
            )}
            {draftRule.rule_type === "weekday_time" && (
              <label>
                Weekdays
                <select multiple value={(draftRule.weekdays || []).map(String)} onChange={(event) => setDraftRule({ ...draftRule, weekdays: Array.from(event.target.selectedOptions).map((option) => Number(option.value)) })}>
                  {WEEKDAY_OPTIONS.map((option) => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              </label>
            )}
            {draftRule.rule_type === "month_date_time" && (
              <TextInput
                label="Month dates"
                value={(draftRule.month_dates || []).join(",")}
                onChange={(value) => setDraftRule({ ...draftRule, month_dates: value.split(",").map((item) => Number(item.trim())).filter((item) => Number.isFinite(item) && item > 0) })}
              />
            )}
            <label>
              Count mode
              <select value={draftRule.count_mode} onChange={(event) => setDraftRule({ ...draftRule, count_mode: event.target.value as ScheduleRule["count_mode"] })}>
                <option value="fixed">Fixed</option>
                <option value="range">Range</option>
              </select>
            </label>
            {draftRule.count_mode === "fixed" ? (
              <TextInput label="Count" type="number" value={String(draftRule.count_value ?? 1)} onChange={(value) => setDraftRule({ ...draftRule, count_value: Number(value) || 1 })} />
            ) : (
              <>
                <TextInput label="Min count" type="number" value={String(draftRule.count_min ?? 1)} onChange={(value) => setDraftRule({ ...draftRule, count_min: Number(value) || 1 })} />
                <TextInput label="Max count" type="number" value={String(draftRule.count_max ?? 2)} onChange={(value) => setDraftRule({ ...draftRule, count_max: Number(value) || 2 })} />
              </>
            )}
            <TextInput label="Label" value={draftRule.label || ""} onChange={(value) => setDraftRule({ ...draftRule, label: value })} />
            <TextInput label="Rule name" value={draftRule.name || ""} onChange={(value) => setDraftRule({ ...draftRule, name: value })} />
          </div>
          {draftRule.delivery_type === "poll" && <label className="check"><input type="checkbox" checked={autoSummary} onChange={(event) => setAutoSummary(event.target.checked)} />Auto-create matching summary rule</label>}
          <label className="check"><input type="checkbox" checked={draftRule.enabled} onChange={(event) => setDraftRule({ ...draftRule, enabled: event.target.checked })} />Enable this rule</label>
          <button className="button button-secondary" type="button" onClick={saveRule}>{editingRuleIndex == null ? "Add rule" : "Save rule"}</button>
        </div>
        <TextInput
          label="Pool threshold percent used"
          type="number"
          value={form.poll_pool_threshold_percent == null ? "" : String(form.poll_pool_threshold_percent)}
          placeholder={`Blank = inherit ${tenant.poll_pool_threshold_percent}%`}
          onChange={(value) => setForm({ ...form, poll_pool_threshold_percent: value.trim() ? Math.max(0, Math.min(100, Number(value))) : null })}
        />
        <label className="check"><input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} />Enable text</label>
        {!editing && <label>Attachment<input type="file" onChange={(event) => setAttachment(event.target.files?.[0] || null)} /></label>}
        <div className="modal-actions">
          <button className="button button-ghost" type="button" onClick={onClose}>Cancel</button>
          <button className="button button-primary" type="submit"><Save size={16} /> {editing ? "Save changes" : "Create text"}</button>
        </div>
      </form>
    </Modal>
  );
}

export function PollModal({
  tenant,
  texts,
  initialPoll,
  onClose,
  onSaved,
  onError,
}: {
  tenant: Tenant;
  texts: Text[];
  initialPoll?: Poll;
  onClose: () => void;
  onSaved: (message: string, pollId?: number) => void;
  onError: (message: string) => void;
}) {
  const editing = Boolean(initialPoll);
  const [form, setForm] = useState<PollFormState>(initialPoll ? pollToForm(initialPoll) : blankPoll(tenant.id, texts[0]));

  function setText(textId: number) {
    const text = texts.find((item) => item.id === textId);
    setForm((current) => ({
      ...current,
      text_id: textId,
      chat_id: text?.chat_id || current.chat_id,
      generated_from_text: text?.body || current.generated_from_text,
    }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!form.text_id) {
      onError("Select a text before saving a poll.");
      return;
    }
    const payload = {
      ...form,
      scheduled_slot: form.scheduled_slot || null,
      sent_at: form.sent_at || null,
      summary_sent_at: form.summary_sent_at || null,
      greenapi_message_id: form.greenapi_message_id || null,
      pool_rank: form.pool_rank == null ? null : Number(form.pool_rank),
      change_window_seconds: form.change_window_seconds == null ? null : Number(form.change_window_seconds),
      auto_lock_seconds: form.auto_lock_seconds == null ? null : Number(form.auto_lock_seconds),
    };
    try {
      if (editing && initialPoll) {
        await api<Poll>(`/polls/${initialPoll.id}`, { method: "PATCH", body: JSON.stringify(payload) });
        onSaved("Poll updated", initialPoll.id);
        return;
      }
      const created = await api<Poll>("/polls", { method: "POST", body: JSON.stringify(payload) });
      onSaved("Poll created", created.id);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to save poll");
    }
  }

  return (
    <Modal title={editing ? "Edit Poll" : "Create Poll"} onClose={onClose}>
      <form className="modal-form" onSubmit={submit}>
        <label>
          Text
          <select value={form.text_id} onChange={(event) => setText(Number(event.target.value))}>
            <option value={0}>Select text</option>
            {texts.map((text) => (
              <option value={text.id} key={text.id}>{text.title}</option>
            ))}
          </select>
        </label>
        <TextInput label="Question" value={form.question} onChange={(value) => setForm({ ...form, question: value })} />
        <div className="time-grid">
          {form.options.map((option, index) => (
            <TextInput key={index} label={`Option ${index + 1}`} value={option} onChange={(value) => {
              const options = [...form.options];
              options[index] = value;
              setForm({ ...form, options });
            }} />
          ))}
        </div>
        <TextInput label="Correct option" value={form.correct_option} onChange={(value) => setForm({ ...form, correct_option: value })} />
        <TextInput label="Status" value={form.status} onChange={(value) => setForm({ ...form, status: value })} />
        <TextInput label="Chat ID" value={form.chat_id} onChange={(value) => setForm({ ...form, chat_id: value })} />
        <TextInput label="Scheduled slot" value={form.scheduled_slot || ""} onChange={(value) => setForm({ ...form, scheduled_slot: value })} />
        <div className="time-grid">
          <TextInput label="Change window minutes" type="number" value={form.change_window_seconds == null ? "" : String(form.change_window_seconds / 60)} placeholder="Blank = no limit" onChange={(value) => setForm({ ...form, change_window_seconds: value.trim() ? Math.max(0, Number(value) * 60) : null })} />
          <TextInput label="Auto-lock minutes" type="number" value={form.auto_lock_seconds == null ? "" : String(form.auto_lock_seconds / 60)} placeholder="Blank = disabled" onChange={(value) => setForm({ ...form, auto_lock_seconds: value.trim() ? Math.max(0, Number(value) * 60) : null })} />
        </div>
        <label className="checkbox-row"><input type="checkbox" checked={form.manual_lock} onChange={(event) => setForm({ ...form, manual_lock: event.target.checked })} /><span>Lock poll manually</span></label>
        <label>Explanation<textarea rows={4} value={form.explanation} onChange={(event) => setForm({ ...form, explanation: event.target.value })} /></label>
        <label>Generated from text<textarea rows={5} value={form.generated_from_text} onChange={(event) => setForm({ ...form, generated_from_text: event.target.value })} /></label>
        <div className="modal-actions">
          <button className="button button-ghost" type="button" onClick={onClose}>Cancel</button>
          <button className="button button-primary" type="submit"><Save size={16} /> {editing ? "Save changes" : "Create poll"}</button>
        </div>
      </form>
    </Modal>
  );
}

export function ScheduleRuleModal({
  initialRule,
  onClose,
  onSaved,
  onError,
}: {
  initialRule?: ScheduleRule;
  onClose: () => void;
  onSaved: (message: string) => void;
  onError: (message: string) => void;
}) {
  const editing = Boolean(initialRule);
  const [form, setForm] = useState<ScheduleRule>(initialRule ? { ...initialRule } : blankScheduleRule());

  async function submit(event: FormEvent) {
    event.preventDefault();
    const payload = {
      name: form.name || null,
      delivery_type: form.delivery_type,
      rule_type: form.rule_type,
      enabled: form.enabled,
      time: form.rule_type === "random_window" ? null : form.time || null,
      weekdays: form.rule_type === "weekday_time" ? form.weekdays || [] : [],
      month_dates: form.rule_type === "month_date_time" ? form.month_dates || [] : [],
      window_start: form.rule_type === "random_window" ? form.window_start || null : null,
      window_end: form.rule_type === "random_window" ? form.window_end || null : null,
      count_mode: form.count_mode,
      count_value: form.count_mode === "fixed" ? form.count_value ?? 1 : null,
      count_min: form.count_mode === "range" ? form.count_min ?? 1 : null,
      count_max: form.count_mode === "range" ? form.count_max ?? 2 : null,
      label: form.label || null,
    };
    try {
      if (editing && initialRule?.id) {
        await api<ScheduleRule>(`/schedule-rules/${initialRule.id}`, { method: "PATCH", body: JSON.stringify(payload) });
        onSaved("Rule updated");
        return;
      }
      await api<ScheduleRule>("/schedule-rules", { method: "POST", body: JSON.stringify(payload) });
      onSaved("Rule created");
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to save rule");
    }
  }

  return (
    <Modal title={editing ? "Edit Rule" : "Create Rule"} onClose={onClose}>
      <form className="modal-form" onSubmit={submit}>
        <TextInput label="Rule name" value={form.name || ""} onChange={(value) => setForm({ ...form, name: value })} />
        <div className="time-grid">
          <label>
            Delivery type
            <select value={form.delivery_type} onChange={(event) => setForm({ ...form, delivery_type: event.target.value as ScheduleRule["delivery_type"] })}>
              <option value="poll">Poll</option>
              <option value="summary">Summary</option>
            </select>
          </label>
          <label>
            Rule type
            <select value={form.rule_type} onChange={(event) => setForm({ ...form, rule_type: event.target.value as ScheduleRule["rule_type"] })}>
              <option value="daily_time">Daily time</option>
              <option value="weekday_time">Weekday time</option>
              <option value="month_date_time">Month date time</option>
              <option value="random_window">Random window</option>
            </select>
          </label>
          {form.rule_type === "random_window" ? (
            <>
              <TextInput label="Window start" value={form.window_start || ""} onChange={(value) => setForm({ ...form, window_start: value })} />
              <TextInput label="Window end" value={form.window_end || ""} onChange={(value) => setForm({ ...form, window_end: value })} />
            </>
          ) : (
            <TextInput label="Time" value={form.time || ""} onChange={(value) => setForm({ ...form, time: value })} />
          )}
          {form.rule_type === "weekday_time" && (
            <label>
              Weekdays
              <select multiple value={(form.weekdays || []).map(String)} onChange={(event) => setForm({ ...form, weekdays: Array.from(event.target.selectedOptions).map((option) => Number(option.value)) })}>
                {WEEKDAY_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
          )}
          {form.rule_type === "month_date_time" && <TextInput label="Month dates" value={(form.month_dates || []).join(",")} onChange={(value) => setForm({ ...form, month_dates: value.split(",").map((item) => Number(item.trim())).filter((item) => Number.isFinite(item) && item > 0) })} />}
          <label>
            Count mode
            <select value={form.count_mode} onChange={(event) => setForm({ ...form, count_mode: event.target.value as ScheduleRule["count_mode"] })}>
              <option value="fixed">Fixed</option>
              <option value="range">Range</option>
            </select>
          </label>
          {form.count_mode === "fixed" ? (
            <TextInput label="Count" type="number" value={String(form.count_value ?? 1)} onChange={(value) => setForm({ ...form, count_value: Number(value) || 1 })} />
          ) : (
            <>
              <TextInput label="Min count" type="number" value={String(form.count_min ?? 1)} onChange={(value) => setForm({ ...form, count_min: Number(value) || 1 })} />
              <TextInput label="Max count" type="number" value={String(form.count_max ?? 2)} onChange={(value) => setForm({ ...form, count_max: Number(value) || 2 })} />
            </>
          )}
          <TextInput label="Label" value={form.label || ""} onChange={(value) => setForm({ ...form, label: value })} />
        </div>
        <label className="check"><input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} />Enable this rule</label>
        <div className="modal-actions">
          <button className="button button-ghost" type="button" onClick={onClose}>Cancel</button>
          <button className="button button-primary" type="submit"><Save size={16} /> {editing ? "Save rule" : "Create rule"}</button>
        </div>
      </form>
    </Modal>
  );
}

export function SettingsModal({
  tenant,
  onClose,
  onSaved,
  onError,
}: {
  tenant: Tenant;
  onClose: () => void;
  onSaved: (message: string) => void;
  onError: (message: string) => void;
}) {
  const [form, setForm] = useState<TenantFormState>(tenantToForm(tenant));

  async function submit(event: FormEvent) {
    event.preventDefault();
    try {
      const connector =
        form.whatsapp_provider === "waha"
          ? {
              provider: "waha",
              config: {
                base_url: form.whatsapp_connector.config.base_url || "",
                session: form.whatsapp_connector.config.session || "",
                api_key: form.whatsapp_connector.config.api_key || "",
              },
            }
          : {
              provider: "greenapi",
              config: {
                api_url: form.whatsapp_connector.config.api_url || form.greenapi_api_url || "",
                id_instance: form.whatsapp_connector.config.id_instance || form.greenapi_id_instance || "",
                api_token_instance:
                  form.whatsapp_connector.config.api_token_instance || form.greenapi_api_token_instance || "",
              },
            };
      await api<Tenant>(`/tenants/${tenant.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          ...form,
          whatsapp_provider: connector.provider,
          whatsapp_connector: connector,
          greenapi_api_url: connector.provider === "greenapi" ? connector.config.api_url : form.greenapi_api_url,
          greenapi_id_instance: connector.provider === "greenapi" ? connector.config.id_instance : form.greenapi_id_instance,
          greenapi_api_token_instance:
            connector.provider === "greenapi" ? connector.config.api_token_instance : form.greenapi_api_token_instance,
        }),
      });
      onSaved("Workspace updated");
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to save workspace");
    }
  }

  return (
    <Modal title="Edit Workspace" onClose={onClose}>
      <form className="modal-form" onSubmit={submit}>
        <TextInput label="Workspace name" value={form.name} onChange={(value) => setForm({ ...form, name: value })} />
        <TextInput label="Username" value={form.username} onChange={(value) => setForm({ ...form, username: value })} />
        <TextInput label="Password" type="password" value={form.password} placeholder="Leave blank to keep current password" onChange={(value) => setForm({ ...form, password: value })} />
        <TextInput label="Pool target size" type="number" value={String(form.poll_pool_target_size)} onChange={(value) => setForm({ ...form, poll_pool_target_size: Math.max(1, Number(value || 1)) })} />
        <TextInput label="Pool refill batch size" type="number" value={String(form.poll_pool_refill_batch_size)} onChange={(value) => setForm({ ...form, poll_pool_refill_batch_size: Math.max(1, Number(value || 1)) })} />
        <TextInput
          label="Pool refill threshold percent used"
          type="number"
          value={String(form.poll_pool_refill_threshold_percent)}
          onChange={(value) => setForm({ ...form, poll_pool_refill_threshold_percent: Math.max(0, Math.min(100, Number(value || 0))) })}
        />
        <label>
          WhatsApp connector
          <select
            value={form.whatsapp_provider}
            onChange={(event) =>
              setForm({
                ...form,
                whatsapp_provider: event.target.value as "greenapi" | "waha",
                whatsapp_connector: {
                  ...form.whatsapp_connector,
                  provider: event.target.value as "greenapi" | "waha",
                },
              })
            }
          >
            <option value="greenapi">GreenAPI</option>
            <option value="waha">WAHA</option>
          </select>
        </label>
        {form.whatsapp_provider === "waha" ? (
          <>
            <TextInput label="WAHA base URL" value={form.whatsapp_connector.config.base_url || ""} onChange={(value) => setForm({ ...form, whatsapp_connector: { ...form.whatsapp_connector, config: { ...form.whatsapp_connector.config, base_url: value } } })} />
            <TextInput label="WAHA session" value={form.whatsapp_connector.config.session || ""} onChange={(value) => setForm({ ...form, whatsapp_connector: { ...form.whatsapp_connector, config: { ...form.whatsapp_connector.config, session: value } } })} />
            <TextInput label="WAHA API key" type="password" value={form.whatsapp_connector.config.api_key || ""} onChange={(value) => setForm({ ...form, whatsapp_connector: { ...form.whatsapp_connector, config: { ...form.whatsapp_connector.config, api_key: value } } })} />
          </>
        ) : (
          <>
            <TextInput label="GreenAPI URL" value={form.whatsapp_connector.config.api_url || form.greenapi_api_url} onChange={(value) => setForm({ ...form, greenapi_api_url: value, whatsapp_connector: { ...form.whatsapp_connector, config: { ...form.whatsapp_connector.config, api_url: value } } })} />
            <TextInput label="GreenAPI instance ID" value={form.whatsapp_connector.config.id_instance || form.greenapi_id_instance} onChange={(value) => setForm({ ...form, greenapi_id_instance: value, whatsapp_connector: { ...form.whatsapp_connector, config: { ...form.whatsapp_connector.config, id_instance: value } } })} />
            <TextInput label="GreenAPI token" type="password" value={form.whatsapp_connector.config.api_token_instance || form.greenapi_api_token_instance} onChange={(value) => setForm({ ...form, greenapi_api_token_instance: value, whatsapp_connector: { ...form.whatsapp_connector, config: { ...form.whatsapp_connector.config, api_token_instance: value } } })} />
          </>
        )}
        <TextInput label="Gemini API key" type="password" value={form.gemini_api_key} onChange={(value) => setForm({ ...form, gemini_api_key: value })} />
        <TextInput label="Gemini model" value={form.gemini_model} onChange={(value) => setForm({ ...form, gemini_model: value })} />
        <TextInput label="Timezone" value={form.timezone} onChange={(value) => setForm({ ...form, timezone: value })} />
        <label className="check"><input type="checkbox" checked={form.summary_enabled} onChange={(event) => setForm({ ...form, summary_enabled: event.target.checked })} />Send summaries</label>
        <label className="check"><input type="checkbox" checked={form.scheduler_enabled} onChange={(event) => setForm({ ...form, scheduler_enabled: event.target.checked })} />Enable scheduler</label>
        <div className="modal-actions">
          <button className="button button-ghost" type="button" onClick={onClose}>Cancel</button>
          <button className="button button-primary" type="submit"><Save size={16} /> Save workspace</button>
        </div>
      </form>
    </Modal>
  );
}

export function PreviewModal({ preview, onClose }: { preview: GeneratedQuestion; onClose: () => void }) {
  return (
    <Modal title="Question Preview" onClose={onClose}>
      <div className="stack">
        <p className="question">{preview.question}</p>
        <div className="stack">
          {preview.options.map((option) => (
            <div className={option === preview.correct_option ? "result-row correct-row" : "result-row"} key={option}>
              <span>{option}</span>
              {option === preview.correct_option && <span className="pill success">Correct</span>}
            </div>
          ))}
        </div>
        <div className="prose-block subtle">{preview.explanation}</div>
      </div>
    </Modal>
  );
}
