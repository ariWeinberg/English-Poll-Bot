import React, { FormEvent, useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Download,
  LogOut,
  Play,
  RefreshCw,
  Save,
  Send,
  Trash2,
} from "lucide-react";
import "./styles.css";

const API_BASE = "/api/v1";
const TOKEN_KEY = "english_bot_token";

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

type PollStats = {
  poll: {
    id: number;
    question: string;
    status: string;
    sent_at?: string | null;
    created_at: string;
  };
  total: number;
  correct_rate: number;
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

const blankTenant: Omit<Tenant, "id"> = {
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

function App() {
  const [token, setToken] = useState(getToken());

  useEffect(() => {
    const onExpired = () => setToken(null);
    window.addEventListener("auth-expired", onExpired);
    return () => window.removeEventListener("auth-expired", onExpired);
  }, []);

  if (!token) {
    return <Login onLogin={(nextToken) => setToken(nextToken)} />;
  }

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
        <label>
          Username
          <input value={username} onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label>
          Password
          <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        <button className="button" type="submit">
          Login
        </button>
      </form>
    </main>
  );
}

function Shell({ onLogout }: { onLogout: () => void }) {
  const [view, setView] = useState<"dashboard" | "texts">("dashboard");
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [tenants, setTenants] = useState<Tenant[]>([]);
  const [texts, setTexts] = useState<Text[]>([]);
  const [pollStats, setPollStats] = useState<PollStats[]>([]);
  const [preview, setPreview] = useState<GeneratedQuestion | null>(null);
  const [toast, setToast] = useState<Toast>(null);
  const [loading, setLoading] = useState(true);

  async function loadData() {
    setLoading(true);
    try {
      const me = await api<Tenant>("/auth/me");
      const [tenantPage, textPage, stats] = await Promise.all([
        api<Page<Tenant>>("/tenants?page_size=100"),
        api<Page<Text>>(`/texts?tenant_id=${me.id}&page_size=100`),
        api<PollStats[]>(`/polls/stats?tenant_id=${me.id}&limit=25`),
      ]);
      setTenant(me);
      setTenants(tenantPage.items);
      setTexts(textPage.items);
      setPollStats(stats);
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

  return (
    <div className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">English WhatsApp Poll Bot</p>
          <h1>{view === "dashboard" ? "Dashboard" : "Texts"}</h1>
          <p>{tenant?.name || "Loading tenant"}</p>
        </div>
        <nav className="nav">
          <button className={view === "dashboard" ? "button" : "button secondary"} onClick={() => setView("dashboard")}>
            Dashboard
          </button>
          <button className={view === "texts" ? "button" : "button secondary"} onClick={() => setView("texts")}>
            Texts
          </button>
          <button
            className="button secondary"
            onClick={() => downloadCsv().catch((err) => setToast({ kind: "error", message: err.message }))}
          >
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
        <Dashboard
          tenant={tenant}
          tenants={tenants}
          pollStats={pollStats}
          preview={preview}
          onTenantChanged={(message) => {
            setToast({ kind: "success", message });
            void loadData();
          }}
        />
      )}

      {view === "texts" && tenant && (
        <Texts
          tenant={tenant}
          texts={texts}
          onChanged={(message) => {
            setToast({ kind: "success", message });
            void loadData();
          }}
          onPreview={(nextPreview) => {
            setPreview(nextPreview);
            setView("dashboard");
          }}
          onError={(message) => setToast({ kind: "error", message })}
        />
      )}
    </div>
  );
}

function Dashboard({
  tenant,
  tenants,
  pollStats,
  preview,
  onTenantChanged,
}: {
  tenant: Tenant;
  tenants: Tenant[];
  pollStats: PollStats[];
  preview: GeneratedQuestion | null;
  onTenantChanged: (message: string) => void;
}) {
  const [form, setForm] = useState<Tenant>(tenant);

  useEffect(() => setForm(tenant), [tenant]);

  async function saveTenant(event: FormEvent) {
    event.preventDefault();
    await api<Tenant>(`/tenants/${form.id}`, {
      method: "PATCH",
      body: JSON.stringify(form),
    });
    onTenantChanged("Tenant saved");
  }

  async function activate(tenantId: number) {
    const result = await api<{ access_token: string }>(`/tenants/${tenantId}/activate`, { method: "POST" });
    localStorage.setItem(TOKEN_KEY, result.access_token);
    onTenantChanged("Tenant activated");
  }

  return (
    <main className="page-grid">
      <section className="panel span-2">
        <div className="panel-header">
          <h2>Tenant</h2>
        </div>
        <form className="config-form" onSubmit={(event) => void saveTenant(event)}>
          <TextInput label="Tenant name" value={form.name} onChange={(value) => setForm({ ...form, name: value })} />
          <TextInput label="Username" value={form.username} onChange={(value) => setForm({ ...form, username: value })} />
          <TextInput
            label="Password"
            type="password"
            value={form.password}
            onChange={(value) => setForm({ ...form, password: value })}
          />
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
          <TextInput
            label="Gemini model"
            value={form.gemini_model}
            onChange={(value) => setForm({ ...form, gemini_model: value })}
          />
          <TextInput label="Timezone" value={form.timezone} onChange={(value) => setForm({ ...form, timezone: value })} />
          <label className="check">
            <input
              type="checkbox"
              checked={form.summary_enabled}
              onChange={(event) => setForm({ ...form, summary_enabled: event.target.checked })}
            />
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
            <input
              type="checkbox"
              checked={form.is_active}
              onChange={(event) => setForm({ ...form, is_active: event.target.checked })}
            />
            Set active tenant
          </label>
          <button className="button form-action" type="submit">
            <Save size={16} /> Save
          </button>
        </form>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Tenants</h2>
        </div>
        <div className="tenant-list">
          {tenants.map((item) => (
            <div className={item.id === tenant.id ? "tenant-pill active" : "tenant-pill"} key={item.id}>
              <span>{item.name}</span>
              {item.id !== tenant.id && (
                <button className="button secondary" onClick={() => void activate(item.id)}>
                  Use
                </button>
              )}
            </div>
          ))}
        </div>
      </section>

      <section className="panel">
        <div className="panel-header">
          <h2>Latest Polls</h2>
        </div>
        <div className="list">
          {pollStats.map((item) => (
            <article className="poll-card" key={item.poll.id}>
              <div className="poll-meta">
                <span>#{item.poll.id}</span>
                <span>{item.poll.status}</span>
                <span>{item.poll.sent_at || item.poll.created_at}</span>
              </div>
              <h3>{item.poll.question}</h3>
              <p>
                <strong>{item.total}</strong> votes <strong>{item.correct_rate.toFixed(1)}%</strong> correct
              </p>
            </article>
          ))}
        </div>
      </section>

      {preview && (
        <section className="panel span-2">
          <div className="panel-header">
            <h2>Preview</h2>
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
  const [form, setForm] = useState({
    title: "",
    body: "",
    chat_id: "",
    morning_time: "08:30",
    evening_time: "18:00",
    summary_time_morning: "08:25",
    summary_time_evening: "17:55",
    enabled: true,
  });

  async function saveText(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    data.set("tenant_id", String(tenant.id));
    data.set("enabled", String(form.enabled));
    await api<Text>("/texts", { method: "POST", body: data });
    setForm({
      title: "",
      body: "",
      chat_id: "",
      morning_time: "08:30",
      evening_time: "18:00",
      summary_time_morning: "08:25",
      summary_time_evening: "17:55",
      enabled: true,
    });
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

  async function sendSummary(textId: number) {
    try {
      const result = await api<{ sent: number }>("/summaries/send-now", {
        method: "POST",
        body: JSON.stringify({ text_id: textId }),
      });
      onChanged(`Sent ${result.sent} summaries`);
    } catch (err) {
      onError(err instanceof Error ? err.message : "Summary send failed");
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
          <h2>New Text</h2>
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
            <TextInput
              label="Morning"
              name="morning_time"
              value={form.morning_time}
              onChange={(value) => setForm({ ...form, morning_time: value })}
            />
            <TextInput
              label="Evening"
              name="evening_time"
              value={form.evening_time}
              onChange={(value) => setForm({ ...form, evening_time: value })}
            />
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
            <input
              type="checkbox"
              checked={form.enabled}
              onChange={(event) => setForm({ ...form, enabled: event.target.checked })}
            />
            Enable text
          </label>
          <label>
            Attachment
            <input name="attachment" type="file" />
          </label>
          <button className="button form-action" type="submit">
            <Save size={16} /> Save
          </button>
        </form>
      </section>

      <section className="panel span-2">
        <div className="panel-header">
          <h2>All Texts</h2>
        </div>
        <div className="list">
          {texts.map((text) => (
            <article className="poll-card" key={text.id}>
              <div className="poll-meta">
                <span>#{text.id}</span>
                <span>{text.title}</span>
                <span>{text.chat_id || "no chat"}</span>
              </div>
              <p className="text-body">{text.body.slice(0, 220)}{text.body.length > 220 ? "..." : ""}</p>
              <div className="actions">
                <button className="button secondary" onClick={() => void preview(text.id)}>
                  <Play size={16} /> Preview
                </button>
                <button className="button" onClick={() => void sendPoll(text.id)}>
                  <Send size={16} /> Poll
                </button>
                <button className="button secondary" onClick={() => void sendSummary(text.id)}>
                  Summary
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
