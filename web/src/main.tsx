import React, { FormEvent, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  BarChart3,
  Download,
  Edit3,
  LogOut,
  Play,
  Plus,
  RefreshCw,
  Save,
  Send,
  Settings,
  Trash2,
} from "lucide-react";
import "./styles.css";

const API_BASE = "/api/v1";
const TOKEN_KEY = "english_bot_token";

type View = "dashboard" | "texts" | "polls" | "settings";

type Tenant = {
  id: number;
  name: string;
  username: string;
  password: string;
  greenapi_api_url: string;
  greenapi_id_instance: string;
  greenapi_api_token_instance: string;
  gemini_api_key: string;
  gemini_model: string;
  timezone: string;
  summary_enabled: boolean;
  scheduler_enabled: boolean;
  is_active: boolean;
};

type Text = {
  id: number;
  tenant_id: number;
  tenant_name: string;
  title: string;
  body: string;
  chat_id: string;
  morning_time: string;
  evening_time: string;
  summary_time_morning: string;
  summary_time_evening: string;
  enabled: boolean;
  attachment_name?: string | null;
};

type Poll = {
  id: number;
  tenant_id: number;
  text_id: number;
  question: string;
  options: string[];
  correct_option: string;
  explanation: string;
  greenapi_message_id?: string | null;
  chat_id: string;
  generated_from_text: string;
  status: string;
  scheduled_slot?: string | null;
  sent_at?: string | null;
  summary_sent_at?: string | null;
  created_at: string;
};

type PollStats = {
  poll: Poll;
  options: string[];
  counts: Record<string, number>;
  total: number;
  correct_count: number;
  correct_rate: number;
};

type VoteEvent = {
  id: number;
  poll_id: number;
  option_name: string;
  voter_wid: string;
  voter_name?: string | null;
  phone_number?: string | null;
  event_type: "vote" | "change" | "unvote";
  previous_option_name?: string | null;
  recorded_at: string;
};

type Page<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  has_next: boolean;
};

type GeneratedQuestion = {
  question: string;
  options: string[];
  correct_option: string;
  explanation: string;
};

type Toast = { kind: "success" | "error"; message: string } | null;

type TextFormState = Omit<Text, "id" | "tenant_name" | "attachment_name">;
type PollFormState = Omit<Poll, "id" | "created_at">;
type TenantFormState = Omit<Tenant, "id">;

const defaultTenantForm: TenantFormState = {
  name: "Tenant",
  username: "",
  password: "",
  greenapi_api_url: "https://api.green-api.com",
  greenapi_id_instance: "",
  greenapi_api_token_instance: "",
  gemini_api_key: "",
  gemini_model: "gemini-3.5-flash",
  timezone: "Asia/Jerusalem",
  summary_enabled: true,
  scheduler_enabled: true,
  is_active: true,
};

function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (response.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    window.dispatchEvent(new Event("auth-expired"));
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // Keep the status text when the response is not JSON.
    }
    throw new Error(detail);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function downloadCsv() {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const response = await fetch(`${API_BASE}/polls/export.csv`, { headers });
  if (!response.ok) throw new Error("CSV export failed");
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "poll-stats.csv";
  link.click();
  URL.revokeObjectURL(url);
}

function blankText(tenantId: number): TextFormState {
  return {
    tenant_id: tenantId,
    title: "",
    body: "",
    chat_id: "",
    morning_time: "08:30",
    evening_time: "18:00",
    summary_time_morning: "08:25",
    summary_time_evening: "17:55",
    enabled: true,
  };
}

function blankPoll(tenantId: number, text?: Text): PollFormState {
  return {
    tenant_id: tenantId,
    text_id: text?.id || 0,
    question: "",
    options: ["A", "B", "C", "D"],
    correct_option: "A",
    explanation: "",
    greenapi_message_id: "",
    chat_id: text?.chat_id || "",
    generated_from_text: text?.body || "",
    status: "draft",
    scheduled_slot: "",
    sent_at: "",
    summary_sent_at: "",
  };
}

function tenantToForm(tenant: Tenant): TenantFormState {
  const { id: _id, ...form } = tenant;
  return form;
}

function textToForm(text: Text): TextFormState {
  return {
    tenant_id: text.tenant_id,
    title: text.title,
    body: text.body,
    chat_id: text.chat_id,
    morning_time: text.morning_time,
    evening_time: text.evening_time,
    summary_time_morning: text.summary_time_morning,
    summary_time_evening: text.summary_time_evening,
    enabled: text.enabled,
  };
}

function pollToForm(poll: Poll): PollFormState {
  return {
    tenant_id: poll.tenant_id,
    text_id: poll.text_id,
    question: poll.question,
    options: poll.options,
    correct_option: poll.correct_option,
    explanation: poll.explanation,
    greenapi_message_id: poll.greenapi_message_id || "",
    chat_id: poll.chat_id,
    generated_from_text: poll.generated_from_text,
    status: poll.status,
    scheduled_slot: poll.scheduled_slot || "",
    sent_at: poll.sent_at || "",
    summary_sent_at: poll.summary_sent_at || "",
  };
}

function App() {
  const [token, setToken] = useState(getToken());

  useEffect(() => {
    const onExpired = () => setToken(null);
    window.addEventListener("auth-expired", onExpired);
    return () => window.removeEventListener("auth-expired", onExpired);
  }, []);

  if (!token) return <Login onLogin={(nextToken) => setToken(nextToken)} />;
  return <Shell onLogout={() => setToken(null)} />;
}

function Login({ onLogin }: { onLogin: (token: string) => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin");
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    try {
      const result = await api<{ access_token: string }>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username, password }),
      });
      localStorage.setItem(TOKEN_KEY, result.access_token);
      onLogin(result.access_token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    }
  }

  return (
    <main className="login-screen">
      <form className="login-panel" onSubmit={submit}>
        <div>
          <p className="eyebrow">English WhatsApp Poll Bot</p>
          <h1>Admin login</h1>
        </div>
        {error && <div className="alert error">{error}</div>}
        <TextInput label="Username" value={username} onChange={setUsername} />
        <TextInput label="Password" type="password" value={password} onChange={setPassword} />
        <button className="button" type="submit">
          Login
        </button>
      </form>
    </main>
  );
}

function Shell({ onLogout }: { onLogout: () => void }) {
  const [view, setView] = useState<View>("dashboard");
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [texts, setTexts] = useState<Text[]>([]);
  const [polls, setPolls] = useState<Poll[]>([]);
  const [pollStats, setPollStats] = useState<PollStats[]>([]);
  const [voteEvents, setVoteEvents] = useState<VoteEvent[]>([]);
  const [preview, setPreview] = useState<GeneratedQuestion | null>(null);
  const [toast, setToast] = useState<Toast>(null);
  const [loading, setLoading] = useState(true);

  async function loadData() {
    setLoading(true);
    try {
      const me = await api<Tenant>("/auth/me");
      const [tenantPage, textPage, pollPage, stats, votePage] = await Promise.all([
        api<Page<Tenant>>("/tenants?page_size=100"),
        api<Page<Text>>(`/texts?tenant_id=${me.id}&page_size=100`),
        api<Page<Poll>>(`/polls?tenant_id=${me.id}&page_size=100`),
        api<PollStats[]>(`/polls/stats?tenant_id=${me.id}&limit=50`),
        api<Page<VoteEvent>>(`/poll-vote-events?tenant_id=${me.id}&page_size=100`),
      ]);
      setTenant(me);
      setTenants(tenantPage.items);
      setTexts(textPage.items);
      setPolls(pollPage.items);
      setPollStats(stats);
      setVoteEvents(votePage.items);
    } catch (err) {
      setToast({ kind: "error", message: err instanceof Error ? err.message : "Failed to load data" });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, []);

  const configured = useMemo(
    () =>
      Boolean(
        tenant?.greenapi_api_url &&
          tenant.greenapi_id_instance &&
          tenant.greenapi_api_token_instance &&
          tenant.gemini_api_key,
      ),
    [tenant],
  );

  function logout() {
    localStorage.removeItem(TOKEN_KEY);
    onLogout();
  }

  function handleSuccess(message: string) {
    setToast({ kind: "success", message });
    void loadData();
  }

  function handleError(message: string) {
    setToast({ kind: "error", message });
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">English WhatsApp Poll Bot</p>
          <h1>{viewTitle(view)}</h1>
          <p>{tenant?.name || "Loading tenant"}</p>
        </div>
        <nav className="nav">
          <NavButton active={view === "dashboard"} onClick={() => setView("dashboard")}>
            Dashboard
          </NavButton>
          <NavButton active={view === "texts"} onClick={() => setView("texts")}>
            Texts
          </NavButton>
          <NavButton active={view === "polls"} onClick={() => setView("polls")}>
            Polls
          </NavButton>
          <NavButton active={view === "settings"} onClick={() => setView("settings")}>
            <Settings size={16} /> Settings
          </NavButton>
          <button className="button secondary" onClick={() => downloadCsv().catch((err) => handleError(err.message))}>
            <Download size={16} /> CSV
          </button>
          <button className="icon-button" onClick={() => void loadData()} title="Refresh">
            <RefreshCw size={18} />
          </button>
          <button className="icon-button" onClick={logout} title="Logout">
            <LogOut size={18} />
          </button>
        </nav>
      </header>

      {toast && <div className={`alert ${toast.kind}`}>{toast.message}</div>}
      {!configured && !loading && <div className="alert warning">This tenant still needs GreenAPI and Gemini settings.</div>}

      {view === "dashboard" && tenant && (
        <Dashboard tenant={tenant} texts={texts} polls={polls} pollStats={pollStats} preview={preview} />
      )}

      {view === "texts" && tenant && (
        <Texts
          tenant={tenant}
          texts={texts}
          onChanged={handleSuccess}
          onPreview={(nextPreview) => {
            setPreview(nextPreview);
            setView("dashboard");
          }}
          onError={handleError}
        />
      )}

      {view === "polls" && tenant && (
        <Polls
          tenant={tenant}
          texts={texts}
          polls={polls}
          voteEvents={voteEvents}
          onChanged={handleSuccess}
          onError={handleError}
        />
      )}

      {view === "settings" && tenant && (
        <SettingsPage
          tenant={tenant}
          tenants={tenants}
          onChanged={handleSuccess}
          onActivated={(token) => {
            localStorage.setItem(TOKEN_KEY, token);
            handleSuccess("Tenant activated");
          }}
        />
      )}
    </div>
  );
}

function viewTitle(view: View) {
  if (view === "texts") return "Texts";
  if (view === "polls") return "Polls";
  if (view === "settings") return "Settings";
  return "Dashboard";
}

function NavButton({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button className={active ? "button" : "button secondary"} onClick={onClick}>
      {children}
    </button>
  );
}

function Dashboard({
  tenant,
  texts,
  polls,
  pollStats,
  preview,
}: {
  tenant: Tenant;
  texts: Text[];
  polls: Poll[];
  pollStats: PollStats[];
  preview: GeneratedQuestion | null;
}) {
  const totalVotes = pollStats.reduce((sum, item) => sum + item.total, 0);
  const averageCorrect =
    pollStats.length === 0 ? 0 : pollStats.reduce((sum, item) => sum + item.correct_rate, 0) / pollStats.length;
  const sentPolls = polls.filter((poll) => poll.status === "sent").length;

  return (
    <main className="dashboard-grid">
      <section className="metric-card">
        <span>Texts</span>
        <strong>{texts.length}</strong>
      </section>
      <section className="metric-card">
        <span>Polls</span>
        <strong>{polls.length}</strong>
      </section>
      <section className="metric-card">
        <span>Sent polls</span>
        <strong>{sentPolls}</strong>
      </section>
      <section className="metric-card">
        <span>Total votes</span>
        <strong>{totalVotes}</strong>
      </section>
      <section className="metric-card">
        <span>Avg correct</span>
        <strong>{averageCorrect.toFixed(1)}%</strong>
      </section>

      <section className="panel span-2">
        <div className="panel-header">
          <h2>
            <BarChart3 size={18} /> Poll Stats
          </h2>
        </div>
        <div className="stats-list">
          {pollStats.map((item) => (
            <article className="poll-card" key={item.poll.id}>
              <div className="poll-meta">
                <span>#{item.poll.id}</span>
                <span>{item.poll.status}</span>
                <span>{item.poll.sent_at || item.poll.created_at}</span>
              </div>
              <h3>{item.poll.question}</h3>
              <div className="stat-row">
                <strong>{item.total}</strong> votes
                <strong>{item.correct_count}</strong> correct
                <strong>{item.correct_rate.toFixed(1)}%</strong> correct rate
              </div>
              <div className="option-stats">
                {item.options.map((option) => (
                  <div className={option === item.poll.correct_option ? "option-stat correct-option" : "option-stat"} key={option}>
                    <span>{option}</span>
                    <strong>{item.counts[option] || 0}</strong>
                  </div>
                ))}
              </div>
            </article>
          ))}
          {pollStats.length === 0 && <p className="empty">No poll stats yet.</p>}
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Tenant Status</h2>
        </div>
        <div className="status-list">
          <Status label="Tenant" value={tenant.name} />
          <Status label="Scheduler" value={tenant.scheduler_enabled ? "Enabled" : "Disabled"} />
          <Status label="Summaries" value={tenant.summary_enabled ? "Enabled" : "Disabled"} />
          <Status label="Timezone" value={tenant.timezone} />
        </div>
      </section>

      {preview && (
        <section className="panel span-2">
          <div className="panel-header">
            <h2>Question Preview</h2>
          </div>
          <p className="question">{preview.question}</p>
          <ol>
            {preview.options.map((option) => (
              <li className={option === preview.correct_option ? "correct" : ""} key={option}>
                {option}
              </li>
            ))}
          </ol>
          <p>{preview.explanation}</p>
        </section>
      )}
    </main>
  );
}

function Status({ label, value }: { label: string; value: string }) {
  return (
    <div className="status-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function describeVoteEvent(event: VoteEvent) {
  if (event.event_type === "unvote") {
    return `retracted vote from ${event.previous_option_name || "unknown option"}`;
  }
  if (event.event_type === "change") {
    return `changed ${event.previous_option_name || "unknown option"} -> ${event.option_name}`;
  }
  return `voted ${event.option_name}`;
}

function formatVoteContact(event: VoteEvent) {
  const name = event.voter_name?.trim();
  const phone = event.phone_number?.trim();
  if (name && phone) return `${name} (${phone})`;
  if (name) return name;
  if (phone) return phone;
  return event.voter_wid;
}

function Texts({
  tenant,
  texts,
  onChanged,
  onPreview,
  onError,
}: {
  tenant: Tenant;
  texts: Text[];
  onChanged: (message: string) => void;
  onPreview: (preview: GeneratedQuestion) => void;
  onError: (message: string) => void;
}) {
  const [editing, setEditing] = useState<Text | null>(null);
  const [form, setForm] = useState<TextFormState>(blankText(tenant.id));

  useEffect(() => {
    if (!editing) setForm(blankText(tenant.id));
  }, [tenant.id, editing]);

  function edit(text: Text) {
    setEditing(text);
    setForm(textToForm(text));
  }

  async function saveText(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (editing) {
      await api<Text>(`/texts/${editing.id}`, { method: "PATCH", body: JSON.stringify(form) });
      setEditing(null);
      setForm(blankText(tenant.id));
      onChanged("Text updated");
      return;
    }

    const data = new FormData(event.currentTarget);
    data.set("tenant_id", String(tenant.id));
    data.set("enabled", String(form.enabled));
    await api<Text>("/texts", { method: "POST", body: data });
    setForm(blankText(tenant.id));
    event.currentTarget.reset();
    onChanged("Text saved");
  }

  async function preview(textId: number) {
    try {
      const result = await api<GeneratedQuestion>("/questions/preview", {
        method: "POST",
        body: JSON.stringify({ text_id: textId }),
      });
      onPreview(result);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Preview failed");
    }
  }

  async function sendPoll(textId: number) {
    try {
      await api("/polls/send-now", { method: "POST", body: JSON.stringify({ text_id: textId, scheduled_slot: "manual" }) });
      onChanged("Poll sent");
    } catch (err) {
      onError(err instanceof Error ? err.message : "Poll send failed");
    }
  }

  async function remove(textId: number) {
    await api(`/texts/${textId}`, { method: "DELETE" });
    onChanged("Text deleted");
  }

  return (
    <main className="page-grid">
      <section className="panel">
        <div className="panel-header">
          <h2>{editing ? "Edit Text" : "New Text"}</h2>
          {editing && (
            <button className="button secondary" onClick={() => setEditing(null)}>
              <Plus size={16} /> New
            </button>
          )}
        </div>
        <form className="config-form single" onSubmit={(event) => void saveText(event)}>
          <TextInput label="Title" name="title" value={form.title} onChange={(value) => setForm({ ...form, title: value })} />
          <label>
            Body
            <textarea name="body" rows={10} value={form.body} onChange={(event) => setForm({ ...form, body: event.target.value })} />
          </label>
          <TextInput
            label="WhatsApp group chat ID"
            name="chat_id"
            value={form.chat_id}
            onChange={(value) => setForm({ ...form, chat_id: value })}
          />
          <div className="time-grid">
            <TextInput label="Morning" name="morning_time" value={form.morning_time} onChange={(value) => setForm({ ...form, morning_time: value })} />
            <TextInput label="Evening" name="evening_time" value={form.evening_time} onChange={(value) => setForm({ ...form, evening_time: value })} />
            <TextInput
              label="AM summary"
              name="summary_time_morning"
              value={form.summary_time_morning}
              onChange={(value) => setForm({ ...form, summary_time_morning: value })}
            />
            <TextInput
              label="PM summary"
              name="summary_time_evening"
              value={form.summary_time_evening}
              onChange={(value) => setForm({ ...form, summary_time_evening: value })}
            />
          </div>
          <label className="check">
            <input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} />
            Enable text
          </label>
          {!editing && (
            <label>
              Attachment
              <input name="attachment" type="file" />
            </label>
          )}
          <button className="button form-action" type="submit">
            <Save size={16} /> {editing ? "Update" : "Save"}
          </button>
        </form>
      </section>

      <section className="panel span-2">
        <div className="panel-header">
          <h2>Texts</h2>
        </div>
        <div className="list">
          {texts.map((text) => (
            <article className="poll-card" key={text.id}>
              <div className="poll-meta">
                <span>#{text.id}</span>
                <span>{text.title}</span>
                <span>{text.enabled ? "enabled" : "disabled"}</span>
                <span>{text.chat_id || "no chat"}</span>
              </div>
              <p className="text-body">
                {text.body.slice(0, 220)}
                {text.body.length > 220 ? "..." : ""}
              </p>
              <div className="actions">
                <button className="button secondary" onClick={() => edit(text)}>
                  <Edit3 size={16} /> Edit
                </button>
                <button className="button secondary" onClick={() => void preview(text.id)}>
                  <Play size={16} /> Preview
                </button>
                <button className="button" onClick={() => void sendPoll(text.id)}>
                  <Send size={16} /> Poll
                </button>
                <button className="icon-button danger" onClick={() => void remove(text.id)} title="Delete">
                  <Trash2 size={18} />
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}

function Polls({
  tenant,
  texts,
  polls,
  voteEvents,
  onChanged,
  onError,
}: {
  tenant: Tenant;
  texts: Text[];
  polls: Poll[];
  voteEvents: VoteEvent[];
  onChanged: (message: string) => void;
  onError: (message: string) => void;
}) {
  const [editing, setEditing] = useState<Poll | null>(null);
  const [form, setForm] = useState<PollFormState>(blankPoll(tenant.id, texts[0]));

  useEffect(() => {
    if (!editing) setForm(blankPoll(tenant.id, texts[0]));
  }, [tenant.id, texts, editing]);

  function setText(textId: number) {
    const text = texts.find((item) => item.id === textId);
    setForm({
      ...form,
      text_id: textId,
      chat_id: text?.chat_id || form.chat_id,
      generated_from_text: text?.body || form.generated_from_text,
    });
  }

  function edit(poll: Poll) {
    setEditing(poll);
    setForm(pollToForm(poll));
  }

  async function savePoll(event: FormEvent) {
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
    };
    if (editing) {
      await api<Poll>(`/polls/${editing.id}`, { method: "PATCH", body: JSON.stringify(payload) });
      setEditing(null);
      onChanged("Poll updated");
      return;
    }
    await api<Poll>("/polls", { method: "POST", body: JSON.stringify(payload) });
    setForm(blankPoll(tenant.id, texts[0]));
    onChanged("Poll created");
  }

  async function remove(pollId: number) {
    await api(`/polls/${pollId}`, { method: "DELETE" });
    onChanged("Poll deleted");
  }

  return (
    <main className="page-grid">
      <section className="panel">
        <div className="panel-header">
          <h2>{editing ? "Edit Poll" : "New Poll"}</h2>
          {editing && (
            <button className="button secondary" onClick={() => setEditing(null)}>
              <Plus size={16} /> New
            </button>
          )}
        </div>
        <form className="config-form single" onSubmit={(event) => void savePoll(event)}>
          <label>
            Text
            <select value={form.text_id} onChange={(event) => setText(Number(event.target.value))}>
              <option value={0}>Select text</option>
              {texts.map((text) => (
                <option value={text.id} key={text.id}>
                  {text.title}
                </option>
              ))}
            </select>
          </label>
          <TextInput label="Question" value={form.question} onChange={(value) => setForm({ ...form, question: value })} />
          <div className="time-grid">
            {form.options.map((option, index) => (
              <TextInput
                label={`Option ${index + 1}`}
                value={option}
                onChange={(value) => {
                  const options = [...form.options];
                  options[index] = value;
                  setForm({ ...form, options });
                }}
                key={index}
              />
            ))}
          </div>
          <TextInput label="Correct option" value={form.correct_option} onChange={(value) => setForm({ ...form, correct_option: value })} />
          <TextInput label="Status" value={form.status} onChange={(value) => setForm({ ...form, status: value })} />
          <TextInput label="Chat ID" value={form.chat_id} onChange={(value) => setForm({ ...form, chat_id: value })} />
          <TextInput
            label="Scheduled slot"
            value={form.scheduled_slot || ""}
            onChange={(value) => setForm({ ...form, scheduled_slot: value })}
          />
          <label>
            Explanation
            <textarea rows={4} value={form.explanation} onChange={(event) => setForm({ ...form, explanation: event.target.value })} />
          </label>
          <label>
            Generated from text
            <textarea
              rows={6}
              value={form.generated_from_text}
              onChange={(event) => setForm({ ...form, generated_from_text: event.target.value })}
            />
          </label>
          <button className="button form-action" type="submit">
            <Save size={16} /> {editing ? "Update" : "Save"}
          </button>
        </form>
      </section>

      <section className="panel span-2">
        <div className="panel-header">
          <h2>Polls</h2>
        </div>
        <div className="list">
          {polls.map((poll) => (
            <article className="poll-card" key={poll.id}>
              <div className="poll-meta">
                <span>#{poll.id}</span>
                <span>{poll.status}</span>
                <span>text #{poll.text_id}</span>
                <span>{poll.sent_at || poll.created_at}</span>
              </div>
              <h3>{poll.question}</h3>
              <div className="option-stats">
                {poll.options.map((option) => (
                  <div className={option === poll.correct_option ? "option-stat correct-option" : "option-stat"} key={option}>
                    <span>{option}</span>
                  </div>
                ))}
              </div>
              <div className="actions">
                <button className="button secondary" onClick={() => edit(poll)}>
                  <Edit3 size={16} /> Edit
                </button>
                <button className="icon-button danger" onClick={() => void remove(poll.id)} title="Delete">
                  <Trash2 size={18} />
                </button>
              </div>
              <div className="poll-events">
                <h4>Poll Events</h4>
                <div className="list">
                  {voteEvents
                    .filter((event) => event.poll_id === poll.id)
                    .map((event) => (
                      <div className="event-row" key={event.id}>
                        <div className="poll-meta">
                          <span>#{event.id}</span>
                          <span>{event.recorded_at}</span>
                        </div>
                        <div className="vote-row">
                          <span className="vote-pill">{formatVoteContact(event)}</span>
                          <strong>{describeVoteEvent(event)}</strong>
                        </div>
                      </div>
                    ))}
                  {!voteEvents.some((event) => event.poll_id === poll.id) && <p className="empty">No poll events yet.</p>}
                </div>
              </div>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}

function SettingsPage({
  tenant,
  tenants,
  onChanged,
  onActivated,
}: {
  tenant: Tenant;
  tenants: Tenant[];
  onChanged: (message: string) => void;
  onActivated: (token: string) => void;
}) {
  const [editing, setEditing] = useState<Tenant | null>(tenant);
  const [form, setForm] = useState<TenantFormState>(tenantToForm(tenant));

  useEffect(() => {
    setEditing(tenant);
    setForm(tenantToForm(tenant));
  }, [tenant]);

  function newTenant() {
    setEditing(null);
    setForm(defaultTenantForm);
  }

  function editTenant(nextTenant: Tenant) {
    setEditing(nextTenant);
    setForm(tenantToForm(nextTenant));
  }

  async function saveTenant(event: FormEvent) {
    event.preventDefault();
    if (editing) {
      await api<Tenant>(`/tenants/${editing.id}`, { method: "PATCH", body: JSON.stringify(form) });
      onChanged("Tenant updated");
      return;
    }
    await api<Tenant>("/tenants", { method: "POST", body: JSON.stringify(form) });
    onChanged("Tenant created");
  }

  async function activate(tenantId: number) {
    const result = await api<{ access_token: string }>(`/tenants/${tenantId}/activate`, { method: "POST" });
    onActivated(result.access_token);
  }

  async function removeTenant(tenantId: number) {
    await api(`/tenants/${tenantId}`, { method: "DELETE" });
    onChanged("Tenant deleted");
  }

  return (
    <main className="page-grid">
      <section className="panel span-2">
        <div className="panel-header">
          <h2>{editing ? "Edit Tenant" : "New Tenant"}</h2>
          <button className="button secondary" onClick={newTenant}>
            <Plus size={16} /> New
          </button>
        </div>
        <TenantForm form={form} setForm={setForm} onSubmit={saveTenant} submitLabel={editing ? "Update" : "Create"} />
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Tenants</h2>
        </div>
        <div className="tenant-list">
          {tenants.map((item) => (
            <div className={item.id === tenant.id ? "tenant-pill active" : "tenant-pill"} key={item.id}>
              <span>{item.name}</span>
              <div className="actions">
                <button className="button secondary" onClick={() => editTenant(item)}>
                  <Edit3 size={16} /> Edit
                </button>
                {item.id !== tenant.id && (
                  <>
                    <button className="button secondary" onClick={() => void activate(item.id)}>
                      Use
                    </button>
                    <button className="icon-button danger" onClick={() => void removeTenant(item.id)} title="Delete">
                      <Trash2 size={18} />
                    </button>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}

function TenantForm({
  form,
  setForm,
  onSubmit,
  submitLabel,
}: {
  form: TenantFormState;
  setForm: (form: TenantFormState) => void;
  onSubmit: (event: FormEvent) => void;
  submitLabel: string;
}) {
  return (
    <form className="config-form" onSubmit={onSubmit}>
      <TextInput label="Tenant name" value={form.name} onChange={(value) => setForm({ ...form, name: value })} />
      <TextInput label="Username" value={form.username} onChange={(value) => setForm({ ...form, username: value })} />
      <TextInput label="Password" type="password" value={form.password} onChange={(value) => setForm({ ...form, password: value })} />
      <TextInput
        label="GreenAPI URL"
        value={form.greenapi_api_url}
        onChange={(value) => setForm({ ...form, greenapi_api_url: value })}
      />
      <TextInput
        label="GreenAPI instance ID"
        value={form.greenapi_id_instance}
        onChange={(value) => setForm({ ...form, greenapi_id_instance: value })}
      />
      <TextInput
        label="GreenAPI token"
        type="password"
        value={form.greenapi_api_token_instance}
        onChange={(value) => setForm({ ...form, greenapi_api_token_instance: value })}
      />
      <TextInput
        label="Gemini API key"
        type="password"
        value={form.gemini_api_key}
        onChange={(value) => setForm({ ...form, gemini_api_key: value })}
      />
      <TextInput label="Gemini model" value={form.gemini_model} onChange={(value) => setForm({ ...form, gemini_model: value })} />
      <TextInput label="Timezone" value={form.timezone} onChange={(value) => setForm({ ...form, timezone: value })} />
      <label className="check">
        <input type="checkbox" checked={form.summary_enabled} onChange={(event) => setForm({ ...form, summary_enabled: event.target.checked })} />
        Send summaries
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={form.scheduler_enabled}
          onChange={(event) => setForm({ ...form, scheduler_enabled: event.target.checked })}
        />
        Enable scheduler
      </label>
      <label className="check">
        <input type="checkbox" checked={form.is_active} onChange={(event) => setForm({ ...form, is_active: event.target.checked })} />
        Set active tenant
      </label>
      <button className="button form-action" type="submit">
        <Save size={16} /> {submitLabel}
      </button>
    </form>
  );
}

function TextInput({
  label,
  value,
  onChange,
  name,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  name?: string;
  type?: string;
}) {
  return (
    <label>
      {label}
      <input name={name} type={type} value={value} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
