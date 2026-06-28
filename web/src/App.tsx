import React, { FormEvent, useEffect, useMemo, useState } from "react";
import {
  ArrowLeft,
  BarChart3,
  BellRing,
  BookOpen,
  Building2,
  CheckCircle2,
  Download,
  ExternalLink,
  FilePenLine,
  FileText,
  LogOut,
  Menu,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Save,
  Send,
  Settings,
  Sparkles,
  Trash2,
  Users,
  Vote,
  X,
} from "lucide-react";

const API_BASE = "/api/v1";
const TOKEN_KEY = "english_bot_token";

type Tenant = {
  id: number;
  name: string;
  username: string;
  greenapi_api_url: string;
  greenapi_id_instance: string;
  greenapi_api_token_instance: string;
  gemini_api_key: string;
  gemini_model: string;
  timezone: string;
  poll_pool_threshold_percent: number;
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
  poll_pool_threshold_percent?: number | null;
  tenant_poll_pool_threshold_percent?: number;
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
  pool_rank?: number | null;
  change_window_seconds?: number | null;
  manual_lock: boolean;
  auto_lock_seconds?: number | null;
  recipient_snapshot_source?: string | null;
  recipient_snapshot_synced_at?: string | null;
  created_at: string;
};

type PollPool = {
  text_id: number;
  queued_count: number;
  effective_threshold_percent: number;
  refill_when_below: number;
  target_size: number;
  refill_batch_size: number;
  next_poll?: Poll | null;
  items: Poll[];
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
  accepted: boolean;
  ignored_reason?: string | null;
  recorded_at: string;
};

type VoteStatus = {
  poll_id: number;
  voter_wid: string;
  voter_name?: string | null;
  phone_number?: string | null;
  counted_option_name?: string | null;
  first_accepted_at?: string | null;
  updated_at?: string | null;
  latest_ignored_option_name?: string | null;
  latest_ignored_reason?: string | null;
  latest_ignored_at?: string | null;
};

type Page<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  has_next: boolean;
};

type LearnerSummary = {
  voter_wid: string;
  display_name: string;
  phone_number: string;
  total_counted_votes: number;
  total_polls_seen: number;
  correct_count: number;
  incorrect_count: number;
  correct_rate: number;
  accepted_changes_count: number;
  ignored_changes_count: number;
  assigned_polls_count: number;
  responded_polls_count: number;
  missed_polls_count: number;
  response_rate: number;
  first_activity?: string | null;
  latest_activity?: string | null;
};

type LearnerHistoryItem = {
  id: number;
  poll_id: number;
  text_id: number;
  question: string;
  correct_option: string;
  voter_wid: string;
  display_name: string;
  phone_number: string;
  selected_option_name?: string | null;
  previous_option_name?: string | null;
  event_type: "vote" | "change" | "unvote";
  accepted: boolean;
  ignored_reason?: string | null;
  recorded_at: string;
};

type LearnerDetail = {
  learner: LearnerSummary;
  history: LearnerHistoryItem[];
  missed_polls: LearnerMissedPollItem[];
};

type LearnerMissedPollItem = {
  poll_id: number;
  text_id: number;
  question: string;
  sent_at?: string | null;
  recipient_snapshot_source?: string | null;
  recipient_snapshot_synced_at?: string | null;
};

type RosterMember = {
  voter_wid: string;
  display_name: string;
  phone_number: string;
  is_active_in_chat: boolean;
  excluded_from_coverage: boolean;
  last_synced_at?: string | null;
};

type TextRoster = {
  text_id: number;
  chat_id: string;
  last_synced_at?: string | null;
  active_count: number;
  excluded_count: number;
  items: RosterMember[];
};

type PollCoverageItem = {
  voter_wid: string;
  display_name: string;
  phone_number: string;
  assigned_at?: string | null;
};

type PollCoverage = {
  poll_id: number;
  coverage_available: boolean;
  recipient_snapshot_source?: string | null;
  recipient_snapshot_synced_at?: string | null;
  assigned_count: number;
  responded_count: number;
  missed_count: number;
  response_rate: number;
  items: PollCoverageItem[];
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

type DocsSession = {
  docs_token: string;
  token_type: string;
  expires_at: string;
  docs_url: string;
  openapi_url: string;
};

type Toast = { kind: "success" | "error"; message: string } | null;

type TextFormState = Omit<Text, "id" | "tenant_name" | "attachment_name">;
type PollFormState = Omit<Poll, "id" | "created_at">;
type TenantFormState = Omit<Tenant, "id"> & { password: string };
type RegisterFormState = { name: string; username: string; password: string; confirmPassword: string; timezone: string };
type LearnerFilters = {
  search: string;
  textId: string;
  dateFrom: string;
  dateTo: string;
  sortBy:
    | "latest_activity"
    | "total_counted_votes"
    | "correct_rate"
    | "assigned_polls_count"
    | "missed_polls_count"
    | "response_rate";
  sortDir: "asc" | "desc";
};
type Route =
  | { name: "login" }
  | { name: "register" }
  | { name: "dashboard" }
  | { name: "learners" }
  | { name: "learner-detail"; voterWid: string }
  | { name: "texts" }
  | { name: "text-detail"; id: number }
  | { name: "polls" }
  | { name: "poll-detail"; id: number }
  | { name: "doc" }
  | { name: "settings" };

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
  poll_pool_threshold_percent: 80,
  summary_enabled: true,
  scheduler_enabled: true,
  is_active: true,
};

function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

function setToken(token: string | null) {
  if (token) {
    localStorage.setItem(TOKEN_KEY, token);
    return;
  }
  localStorage.removeItem(TOKEN_KEY);
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
    setToken(null);
    window.dispatchEvent(new Event("auth-expired"));
  }
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // Keep status text when body is not JSON.
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
    poll_pool_threshold_percent: null,
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
    change_window_seconds: null,
    manual_lock: false,
    auto_lock_seconds: null,
  };
}

function tenantToForm(tenant: Tenant): TenantFormState {
  const { id: _id, ...rest } = tenant;
  return {
    ...rest,
    password: "",
  };
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
    poll_pool_threshold_percent: text.poll_pool_threshold_percent ?? null,
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
    pool_rank: poll.pool_rank ?? null,
    change_window_seconds: poll.change_window_seconds ?? null,
    manual_lock: poll.manual_lock,
    auto_lock_seconds: poll.auto_lock_seconds ?? null,
  };
}

function normalizePathname(pathname: string) {
  if (!pathname || pathname === "/") return "/";
  return pathname.replace(/\/+$/, "") || "/";
}

function parseRoute(pathname: string): Route {
  const path = normalizePathname(pathname);
  if (path === "/register") return { name: "register" };
  if (path === "/dashboard" || path === "/") return { name: "dashboard" };
  if (path === "/learners") return { name: "learners" };
  if (path === "/texts") return { name: "texts" };
  if (path === "/polls") return { name: "polls" };
  if (path === "/doc") return { name: "doc" };
  if (path === "/settings") return { name: "settings" };
  const learnerMatch = path.match(/^\/learners\/(.+)$/);
  if (learnerMatch) return { name: "learner-detail", voterWid: decodeURIComponent(learnerMatch[1]) };
  const textMatch = path.match(/^\/texts\/(\d+)$/);
  if (textMatch) return { name: "text-detail", id: Number(textMatch[1]) };
  const pollMatch = path.match(/^\/polls\/(\d+)$/);
  if (pollMatch) return { name: "poll-detail", id: Number(pollMatch[1]) };
  return { name: "login" };
}

function routeHref(route: Route): string {
  switch (route.name) {
    case "register":
      return "/register";
    case "dashboard":
      return "/dashboard";
    case "learners":
      return "/learners";
    case "learner-detail":
      return `/learners/${encodeURIComponent(route.voterWid)}`;
    case "texts":
      return "/texts";
    case "text-detail":
      return `/texts/${route.id}`;
    case "polls":
      return "/polls";
    case "poll-detail":
      return `/polls/${route.id}`;
    case "doc":
      return "/doc";
    case "settings":
      return "/settings";
    default:
      return "/login";
  }
}

function navigateTo(route: Route, replace = false) {
  const href = routeHref(route);
  if (replace) window.history.replaceState({}, "", href);
  else window.history.pushState({}, "", href);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

function describeVoteEvent(event: VoteEvent) {
  const suffix = event.accepted ? "" : ` (ignored: ${describeIgnoredReason(event.ignored_reason)})`;
  if (event.event_type === "unvote") {
    return `retracted vote from ${event.previous_option_name || "unknown option"}${suffix}`;
  }
  if (event.event_type === "change") {
    return `changed ${event.previous_option_name || "unknown option"} -> ${event.option_name}${suffix}`;
  }
  return `voted ${event.option_name}${suffix}`;
}

function formatVoteContact(contact: { voter_name?: string | null; phone_number?: string | null; voter_wid: string }) {
  const name = contact.voter_name?.trim();
  const phone = contact.phone_number?.trim();
  if (name && phone) return `${name} (${phone})`;
  if (name) return name;
  if (phone) return phone;
  return contact.voter_wid;
}

function describeIgnoredReason(reason?: string | null) {
  if (reason === "manual_lock") return "poll locked";
  if (reason === "auto_lock_expired") return "auto-lock expired";
  if (reason === "change_window_expired") return "change window expired";
  return "rule blocked";
}

function minutesLabel(seconds?: number | null) {
  if (seconds == null) return "No limit";
  return `${Math.floor(seconds / 60)} min`;
}

function excerpt(value: string, length = 160) {
  if (value.length <= length) return value;
  return `${value.slice(0, length)}...`;
}

function formatWhen(value?: string | null) {
  return value || "Not sent yet";
}

function formatActivity(value?: string | null) {
  return value || "—";
}

function formatSnapshotSource(value?: string | null) {
  if (value === "live_sync") return "Live sync";
  if (value === "cached_roster") return "Cached roster";
  if (value === "unavailable") return "Unavailable";
  return value || "Unavailable";
}

function learnerQueryString(tenantId: number, filters: LearnerFilters, extra?: Record<string, string | number | undefined>) {
  const params = new URLSearchParams();
  params.set("tenant_id", String(tenantId));
  params.set("sort_by", filters.sortBy);
  params.set("sort_dir", filters.sortDir);
  if (filters.search.trim()) params.set("search", filters.search.trim());
  if (filters.textId) params.set("text_id", filters.textId);
  if (filters.dateFrom) params.set("date_from", filters.dateFrom);
  if (filters.dateTo) params.set("date_to", filters.dateTo);
  Object.entries(extra || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== "") params.set(key, String(value));
  });
  return params.toString();
}

export function App() {
  const [token, setTokenState] = useState(getToken());
  const [route, setRoute] = useState<Route>(parseRoute(window.location.pathname));

  useEffect(() => {
    const onRoute = () => setRoute(parseRoute(window.location.pathname));
    const onExpired = () => {
      setTokenState(null);
      navigateTo({ name: "login" }, true);
    };
    window.addEventListener("popstate", onRoute);
    window.addEventListener("auth-expired", onExpired);
    return () => {
      window.removeEventListener("popstate", onRoute);
      window.removeEventListener("auth-expired", onExpired);
    };
  }, []);

  useEffect(() => {
    if (!token) {
      if (route.name !== "register" && route.name !== "login") {
        navigateTo({ name: "login" }, true);
      }
      return;
    }
    if (route.name === "login" || route.name === "register") {
      navigateTo({ name: "dashboard" }, true);
    }
  }, [token, route.name]);

  function handleAuth(nextToken: string) {
    setToken(nextToken);
    setTokenState(nextToken);
    navigateTo({ name: "dashboard" }, true);
  }

  if (!token) {
    if (route.name === "register") {
      return <RegisterPage onRegistered={handleAuth} onLoginLink={() => navigateTo({ name: "login" })} />;
    }
    return <LoginPage onLogin={handleAuth} onRegisterLink={() => navigateTo({ name: "register" })} />;
  }

  return <AuthenticatedApp route={route} onLogout={() => setTokenState(null)} />;
}

function LoginPage({ onLogin, onRegisterLink }: { onLogin: (token: string) => void; onRegisterLink: () => void }) {
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
      onLogin(result.access_token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    }
  }

  return (
    <PublicLayout
      eyebrow="English WhatsApp Poll Bot"
      title="Run smarter learning polls"
      subtitle="A sharper admin experience for texts, polls, summaries, and tenant configuration."
    >
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-card-header">
          <h2>Login</h2>
          <p>Access your workspace and manage one tenant from a cleaner app shell.</p>
        </div>
        {error && <div className="alert error">{error}</div>}
        <TextInput label="Username" value={username} onChange={setUsername} />
        <TextInput label="Password" type="password" value={password} onChange={setPassword} />
        <button className="button button-primary" type="submit">
          Login
        </button>
        <button className="button button-ghost" type="button" onClick={onRegisterLink}>
          Create workspace
        </button>
      </form>
    </PublicLayout>
  );
}

function RegisterPage({ onRegistered, onLoginLink }: { onRegistered: (token: string) => void; onLoginLink: () => void }) {
  const [form, setForm] = useState<RegisterFormState>({
    name: "",
    username: "",
    password: "",
    confirmPassword: "",
    timezone: "Asia/Jerusalem",
  });
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError("");
    if (form.password !== form.confirmPassword) {
      setError("Passwords do not match.");
      return;
    }
    try {
      const result = await api<{ access_token: string }>("/auth/register", {
        method: "POST",
        body: JSON.stringify({
          name: form.name,
          username: form.username,
          password: form.password,
          timezone: form.timezone,
        }),
      });
      onRegistered(result.access_token);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    }
  }

  return (
    <PublicLayout
      eyebrow="Tenant Registration"
      title="Create your workspace"
      subtitle="Register a tenant, sign in immediately, and finish configuration from a dedicated settings page."
    >
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-card-header">
          <h2>Register</h2>
          <p>Tenant creation is now a public onboarding flow, not an in-app settings action.</p>
        </div>
        {error && <div className="alert error">{error}</div>}
        <TextInput label="Workspace name" value={form.name} onChange={(value) => setForm({ ...form, name: value })} />
        <TextInput label="Username" value={form.username} onChange={(value) => setForm({ ...form, username: value })} />
        <TextInput
          label="Password"
          type="password"
          value={form.password}
          onChange={(value) => setForm({ ...form, password: value })}
        />
        <TextInput
          label="Confirm password"
          type="password"
          value={form.confirmPassword}
          onChange={(value) => setForm({ ...form, confirmPassword: value })}
        />
        <TextInput label="Timezone" value={form.timezone} onChange={(value) => setForm({ ...form, timezone: value })} />
        <button className="button button-primary" type="submit">
          Register workspace
        </button>
        <button className="button button-ghost" type="button" onClick={onLoginLink}>
          Back to login
        </button>
      </form>
    </PublicLayout>
  );
}

function PublicLayout({
  eyebrow,
  title,
  subtitle,
  children,
}: {
  eyebrow: string;
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <main className="public-screen">
      <section className="public-hero">
        <div className="hero-copy">
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
          <p className="hero-subtitle">{subtitle}</p>
          <div className="hero-points">
            <HeroPoint icon={<Sparkles size={16} />} label="Refined dashboard and detail views" />
            <HeroPoint icon={<Building2 size={16} />} label="Tenant onboarding through registration" />
            <HeroPoint icon={<CheckCircle2 size={16} />} label="Floating create and edit workflows" />
          </div>
        </div>
        {children}
      </section>
    </main>
  );
}

function HeroPoint({ icon, label }: { icon: React.ReactNode; label: string }) {
  return (
    <div className="hero-point">
      <span>{icon}</span>
      <span>{label}</span>
    </div>
  );
}

function AuthenticatedApp({ route, onLogout }: { route: Route; onLogout: () => void }) {
  const [tenant, setTenant] = useState<Tenant | null>(null);
  const [texts, setTexts] = useState<Text[]>([]);
  const [polls, setPolls] = useState<Poll[]>([]);
  const [pollStats, setPollStats] = useState<PollStats[]>([]);
  const [voteEvents, setVoteEvents] = useState<VoteEvent[]>([]);
  const [currentVoteStatus, setCurrentVoteStatus] = useState<VoteStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<Toast>(null);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [textModal, setTextModal] = useState<{ mode: "create" | "edit"; text?: Text } | null>(null);
  const [pollModal, setPollModal] = useState<{ mode: "create" | "edit"; poll?: Poll } | null>(null);
  const [settingsModalOpen, setSettingsModalOpen] = useState(false);
  const [preview, setPreview] = useState<GeneratedQuestion | null>(null);
  const [currentPool, setCurrentPool] = useState<PollPool | null>(null);
  const [currentRoster, setCurrentRoster] = useState<TextRoster | null>(null);
  const [currentCoverage, setCurrentCoverage] = useState<PollCoverage | null>(null);
  const [learnerFilters, setLearnerFilters] = useState<LearnerFilters>({
    search: "",
    textId: "",
    dateFrom: "",
    dateTo: "",
    sortBy: "latest_activity",
    sortDir: "desc",
  });

  async function loadData() {
    setLoading(true);
    try {
      const me = await api<Tenant>("/auth/me");
      const [textPage, pollPage, stats, votePage, pool] = await Promise.all([
        api<Page<Text>>(`/texts?tenant_id=${me.id}&page_size=100`),
        api<Page<Poll>>(`/polls?tenant_id=${me.id}&page_size=100`),
        api<PollStats[]>(`/polls/stats?tenant_id=${me.id}&limit=100`),
        api<Page<VoteEvent>>(`/poll-vote-events?tenant_id=${me.id}&page_size=200`),
        route.name === "text-detail" ? api<PollPool>(`/texts/${route.id}/poll-pool`) : Promise.resolve(null),
      ]);
      const [roster, coverage] = await Promise.all([
        route.name === "text-detail" ? api<TextRoster>(`/texts/${route.id}/roster`) : Promise.resolve(null),
        route.name === "poll-detail" ? api<PollCoverage>(`/polls/${route.id}/coverage?page_size=50`) : Promise.resolve(null),
      ]);
      setTenant(me);
      setTexts(textPage.items);
      setPolls(pollPage.items);
      setPollStats(stats);
      setVoteEvents(votePage.items);
      setCurrentPool(pool);
      setCurrentRoster(roster);
      setCurrentCoverage(coverage);
    } catch (err) {
      setToast({ kind: "error", message: err instanceof Error ? err.message : "Failed to load workspace" });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadData();
  }, [route.name, route.name === "text-detail" ? route.id : null]);

  useEffect(() => {
    setMobileNavOpen(false);
  }, [route]);

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

  const currentText = route.name === "text-detail" ? texts.find((item) => item.id === route.id) || null : null;
  const currentPoll = route.name === "poll-detail" ? polls.find((item) => item.id === route.id) || null : null;
  const currentPollStats = currentPoll ? pollStats.find((item) => item.poll.id === currentPoll.id) || null : null;
  const currentPollEvents = currentPoll ? voteEvents.filter((item) => item.poll_id === currentPoll.id) : [];

  useEffect(() => {
    if (!currentPoll) {
      setCurrentVoteStatus([]);
      return;
    }
    api<VoteStatus[]>(`/polls/${currentPoll.id}/vote-status`)
      .then(setCurrentVoteStatus)
      .catch((err) => handleError(err instanceof Error ? err.message : "Failed to load vote status"));
  }, [currentPoll?.id]);

  function handleLogout() {
    setToken(null);
    onLogout();
    navigateTo({ name: "login" }, true);
  }

  function handleSuccess(message: string) {
    setToast({ kind: "success", message });
    void loadData();
  }

  function handleError(message: string) {
    setToast({ kind: "error", message });
  }

  async function handlePreview(textId: number) {
    try {
      const result = await api<GeneratedQuestion>("/questions/preview", {
        method: "POST",
        body: JSON.stringify({ text_id: textId }),
      });
      setPreview(result);
    } catch (err) {
      handleError(err instanceof Error ? err.message : "Preview failed");
    }
  }

  async function handleSendPoll(textId: number) {
    try {
      await api("/polls/send-now", { method: "POST", body: JSON.stringify({ text_id: textId, scheduled_slot: "manual" }) });
      handleSuccess("Poll sent");
    } catch (err) {
      handleError(err instanceof Error ? err.message : "Poll send failed");
    }
  }

  async function handleRefillPool(textId: number) {
    try {
      const result = await api<PollPool>(`/texts/${textId}/poll-pool/refill`, { method: "POST" });
      setCurrentPool(result);
      handleSuccess("Poll pool refilled");
    } catch (err) {
      handleError(err instanceof Error ? err.message : "Poll pool refill failed");
    }
  }

  async function handleSyncRoster(textId: number) {
    try {
      const result = await api<TextRoster>(`/texts/${textId}/roster/sync`, { method: "POST" });
      setCurrentRoster(result);
      handleSuccess("Roster synced");
    } catch (err) {
      handleError(err instanceof Error ? err.message : "Roster sync failed");
    }
  }

  async function handleToggleRosterExclusion(textId: number, voterWid: string, excluded: boolean) {
    try {
      await api<RosterMember>(`/texts/${textId}/roster/${encodeURIComponent(voterWid)}`, {
        method: "PATCH",
        body: JSON.stringify({ excluded_from_coverage: excluded }),
      });
      if (route.name === "text-detail" && route.id === textId) {
        const roster = await api<TextRoster>(`/texts/${textId}/roster`);
        setCurrentRoster(roster);
      }
      handleSuccess(excluded ? "Learner excluded from coverage" : "Learner restored to coverage");
    } catch (err) {
      handleError(err instanceof Error ? err.message : "Failed to update roster member");
    }
  }

  async function handleMovePoolPoll(pollId: number, poolRank: number) {
    try {
      await api<Poll>(`/polls/${pollId}/pool-rank`, { method: "PATCH", body: JSON.stringify({ pool_rank: poolRank }) });
      if (currentText) {
        const result = await api<PollPool>(`/texts/${currentText.id}/poll-pool`);
        setCurrentPool(result);
      }
      handleSuccess("Poll order updated");
    } catch (err) {
      handleError(err instanceof Error ? err.message : "Failed to reorder queued poll");
    }
  }

  async function handleOpenSwagger() {
    try {
      const result = await api<DocsSession>("/docs/session", { method: "POST" });
      window.open(result.docs_url, "_blank", "noopener,noreferrer");
      setToast({ kind: "success", message: `Swagger session expires at ${result.expires_at}` });
    } catch (err) {
      handleError(err instanceof Error ? err.message : "Failed to open API docs");
    }
  }

  async function handleDeleteText(textId: number) {
    if (!window.confirm("Delete this text?")) return;
    await api(`/texts/${textId}`, { method: "DELETE" });
    if (route.name === "text-detail" && route.id === textId) navigateTo({ name: "texts" }, true);
    handleSuccess("Text deleted");
  }

  async function handleDeletePoll(pollId: number) {
    if (!window.confirm("Delete this poll?")) return;
    await api(`/polls/${pollId}`, { method: "DELETE" });
    if (route.name === "poll-detail" && route.id === pollId) navigateTo({ name: "polls" }, true);
    handleSuccess("Poll deleted");
  }

  if (loading && !tenant) {
    return <LoadingScreen />;
  }

  if (!tenant) {
    return (
      <div className="empty-state page-shell">
        <h2>Workspace unavailable</h2>
        <p>Unable to load the current tenant.</p>
      </div>
    );
  }

  return (
    <div className="app-frame">
      <Sidebar route={route} open={mobileNavOpen} tenant={tenant} onClose={() => setMobileNavOpen(false)} />
      <div className="frame-main">
        <Topbar
          tenant={tenant}
          route={route}
          configured={configured}
          onMenu={() => setMobileNavOpen(true)}
          onRefresh={() => void loadData()}
          onDownload={() => downloadCsv().catch((err) => handleError(err.message))}
          onLogout={handleLogout}
        />
        {toast && <div className={`alert ${toast.kind}`}>{toast.message}</div>}
        {!configured && <div className="alert warning">Workspace setup is incomplete. Finish GreenAPI and Gemini settings to enable delivery.</div>}
        <div className="page-shell">
          {route.name === "dashboard" && (
            <DashboardPage
              tenant={tenant}
              texts={texts}
              polls={polls}
              pollStats={pollStats}
              onOpenLearners={() => navigateTo({ name: "learners" })}
              onOpenText={(text) => navigateTo({ name: "text-detail", id: text.id })}
              onOpenPoll={(poll) => navigateTo({ name: "poll-detail", id: poll.id })}
              onNewText={() => setTextModal({ mode: "create" })}
              onNewPoll={() => setPollModal({ mode: "create" })}
            />
          )}
          {route.name === "learners" && (
            <LearnersPage
              tenant={tenant}
              texts={texts}
              filters={learnerFilters}
              onFiltersChange={setLearnerFilters}
              onOpenLearner={(learner) => navigateTo({ name: "learner-detail", voterWid: learner.voter_wid })}
            />
          )}
          {route.name === "learner-detail" && (
            <LearnerDetailPage
              tenant={tenant}
              texts={texts}
              voterWid={route.voterWid}
              filters={learnerFilters}
              onBack={() => navigateTo({ name: "learners" })}
            />
          )}
          {route.name === "texts" && (
            <TextsPage
              texts={texts}
              onOpen={(text) => navigateTo({ name: "text-detail", id: text.id })}
              onCreate={() => setTextModal({ mode: "create" })}
              onEdit={(text) => setTextModal({ mode: "edit", text })}
              onPreview={handlePreview}
              onSendPoll={handleSendPoll}
              onDelete={(text) => void handleDeleteText(text.id)}
            />
          )}
          {route.name === "text-detail" && (
            <TextDetailPage
              text={currentText}
              pool={currentPool}
              roster={currentRoster}
              onBack={() => navigateTo({ name: "texts" })}
              onEdit={(text) => setTextModal({ mode: "edit", text })}
              onPreview={handlePreview}
              onSendPoll={handleSendPoll}
              onSyncRoster={handleSyncRoster}
              onToggleRosterExclusion={handleToggleRosterExclusion}
              onRefillPool={handleRefillPool}
              onMovePoolPoll={handleMovePoolPoll}
              onDelete={(text) => void handleDeleteText(text.id)}
              onDeleteQueuedPoll={(poll) => void handleDeletePoll(poll.id)}
            />
          )}
          {route.name === "polls" && (
            <PollsPage
              polls={polls}
              texts={texts}
              pollStats={pollStats}
              onOpen={(poll) => navigateTo({ name: "poll-detail", id: poll.id })}
              onCreate={() => setPollModal({ mode: "create" })}
              onEdit={(poll) => setPollModal({ mode: "edit", poll })}
              onDelete={(poll) => void handleDeletePoll(poll.id)}
            />
          )}
          {route.name === "poll-detail" && (
            <PollDetailPage
              poll={currentPoll}
              stats={currentPollStats}
              coverage={currentCoverage}
              voteStatus={currentVoteStatus}
              events={currentPollEvents}
              onBack={() => navigateTo({ name: "polls" })}
              onEdit={(poll) => setPollModal({ mode: "edit", poll })}
              onDelete={(poll) => void handleDeletePoll(poll.id)}
            />
          )}
          {route.name === "settings" && (
            <SettingsPage tenant={tenant} onEdit={() => setSettingsModalOpen(true)} />
          )}
          {route.name === "doc" && <DocPage onOpenSwagger={() => void handleOpenSwagger()} />}
        </div>
      </div>

      {textModal && (
        <TextModal
          tenant={tenant}
          initialText={textModal.text}
          onClose={() => setTextModal(null)}
          onSaved={(message) => {
            setTextModal(null);
            handleSuccess(message);
          }}
          onError={handleError}
        />
      )}
      {pollModal && (
        <PollModal
          tenant={tenant}
          texts={texts}
          initialPoll={pollModal.poll}
          onClose={() => setPollModal(null)}
          onSaved={(message, pollId) => {
            setPollModal(null);
            handleSuccess(message);
            if (pollId) navigateTo({ name: "poll-detail", id: pollId });
          }}
          onError={handleError}
        />
      )}
      {settingsModalOpen && (
        <SettingsModal
          tenant={tenant}
          onClose={() => setSettingsModalOpen(false)}
          onSaved={(message) => {
            setSettingsModalOpen(false);
            handleSuccess(message);
          }}
          onError={handleError}
        />
      )}
      {preview && <PreviewModal preview={preview} onClose={() => setPreview(null)} />}
    </div>
  );
}

function LoadingScreen() {
  return (
    <div className="loading-screen">
      <div className="loading-card">
        <RefreshCw className="spin" size={20} />
        <span>Loading workspace...</span>
      </div>
    </div>
  );
}

function Sidebar({
  route,
  open,
  tenant,
  onClose,
}: {
  route: Route;
  open: boolean;
  tenant: Tenant;
  onClose: () => void;
}) {
  const items = [
    { icon: <BarChart3 size={18} />, label: "Dashboard", route: { name: "dashboard" } as Route, active: route.name === "dashboard" },
    {
      icon: <Users size={18} />,
      label: "Learners",
      route: { name: "learners" } as Route,
      active: route.name === "learners" || route.name === "learner-detail",
    },
    {
      icon: <FileText size={18} />,
      label: "Texts",
      route: { name: "texts" } as Route,
      active: route.name === "texts" || route.name === "text-detail",
    },
    {
      icon: <Vote size={18} />,
      label: "Polls",
      route: { name: "polls" } as Route,
      active: route.name === "polls" || route.name === "poll-detail",
    },
    { icon: <BookOpen size={18} />, label: "Docs", route: { name: "doc" } as Route, active: route.name === "doc" },
    { icon: <Settings size={18} />, label: "Settings", route: { name: "settings" } as Route, active: route.name === "settings" },
  ];

  return (
    <>
      <div className={open ? "sidebar-backdrop open" : "sidebar-backdrop"} onClick={onClose} />
      <aside className={open ? "sidebar open" : "sidebar"}>
        <div className="sidebar-brand">
          <div className="brand-mark">EP</div>
          <div>
            <strong>English Polls</strong>
            <p>{tenant.name}</p>
          </div>
          <button className="icon-button button-ghost sidebar-close" onClick={onClose} title="Close navigation">
            <X size={18} />
          </button>
        </div>
        <nav className="sidebar-nav">
          {items.map((item) => (
            <button
              className={item.active ? "sidebar-link active" : "sidebar-link"}
              key={item.label}
              onClick={() => navigateTo(item.route)}
            >
              {item.icon}
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="sidebar-note">
            <BellRing size={16} />
            <span>Manage one workspace cleanly from a dedicated shell.</span>
          </div>
        </div>
      </aside>
    </>
  );
}

function Topbar({
  tenant,
  route,
  configured,
  onMenu,
  onRefresh,
  onDownload,
  onLogout,
}: {
  tenant: Tenant;
  route: Route;
  configured: boolean;
  onMenu: () => void;
  onRefresh: () => void;
  onDownload: () => void;
  onLogout: () => void;
}) {
  return (
    <header className="topbar">
      <div className="topbar-left">
        <button className="icon-button button-ghost mobile-only" onClick={onMenu} title="Open navigation">
          <Menu size={18} />
        </button>
        <div>
          <p className="eyebrow">{tenant.name}</p>
          <h1>{routeTitle(route)}</h1>
        </div>
      </div>
      <div className="topbar-actions">
        <div className={configured ? "status-chip ready" : "status-chip"}>{configured ? "Ready" : "Setup needed"}</div>
        <button className="button button-ghost" onClick={onDownload}>
          <Download size={16} /> CSV
        </button>
        <button className="icon-button button-ghost" onClick={onRefresh} title="Refresh">
          <RefreshCw size={18} />
        </button>
        <button className="icon-button button-ghost" onClick={onLogout} title="Logout">
          <LogOut size={18} />
        </button>
      </div>
    </header>
  );
}

function routeTitle(route: Route) {
  switch (route.name) {
    case "learners":
      return "Learners";
    case "learner-detail":
      return "Learner Detail";
    case "texts":
      return "Texts";
    case "text-detail":
      return "Text Detail";
    case "polls":
      return "Polls";
    case "poll-detail":
      return "Poll Detail";
    case "doc":
      return "Operations Docs";
    case "settings":
      return "Workspace Settings";
    default:
      return "Dashboard";
  }
}

function DashboardPage({
  tenant,
  texts,
  polls,
  pollStats,
  onOpenLearners,
  onOpenText,
  onOpenPoll,
  onNewText,
  onNewPoll,
}: {
  tenant: Tenant;
  texts: Text[];
  polls: Poll[];
  pollStats: PollStats[];
  onOpenLearners: () => void;
  onOpenText: (text: Text) => void;
  onOpenPoll: (poll: Poll) => void;
  onNewText: () => void;
  onNewPoll: () => void;
}) {
  const totalVotes = pollStats.reduce((sum, item) => sum + item.total, 0);
  const averageCorrect = pollStats.length === 0 ? 0 : pollStats.reduce((sum, item) => sum + item.correct_rate, 0) / pollStats.length;
  const sentPolls = polls.filter((poll) => poll.status === "sent").length;
  const queuedPolls = polls.filter((poll) => poll.status === "queued").length;

  return (
    <div className="dashboard-layout">
      <section className="hero-panel">
        <div>
          <p className="eyebrow">Workspace Overview</p>
          <h2>{tenant.name}</h2>
          <p className="hero-subtitle">A cleaner command surface for content, delivery, and post-send performance.</p>
        </div>
        <div className="hero-actions">
          <button className="button button-secondary" onClick={onOpenLearners}>
            <Users size={16} /> Learner progress
          </button>
          <button className="button button-primary" onClick={onNewText}>
            <Plus size={16} /> New text
          </button>
          <button className="button button-secondary" onClick={onNewPoll}>
            <Plus size={16} /> New poll
          </button>
        </div>
      </section>

      <section className="metric-grid">
        <MetricCard label="Texts" value={texts.length} detail="Content sources" icon={<FileText size={18} />} />
        <MetricCard label="Polls" value={polls.length} detail="Draft + sent" icon={<Vote size={18} />} />
        <MetricCard label="Queued polls" value={queuedPolls} detail="Ready in pool" icon={<Play size={18} />} />
        <MetricCard label="Sent polls" value={sentPolls} detail="Delivered to groups" icon={<Send size={18} />} />
        <MetricCard label="Total votes" value={totalVotes} detail="Across all tracked polls" icon={<BarChart3 size={18} />} />
        <MetricCard label="Avg correct" value={`${averageCorrect.toFixed(1)}%`} detail="Accuracy rate" icon={<CheckCircle2 size={18} />} />
      </section>

      <div className="content-grid">
        <section className="surface">
          <div className="section-header">
            <div>
              <p className="section-kicker">Recent Texts</p>
              <h3>Source content</h3>
            </div>
          </div>
          <div className="stack">
            {texts.slice(0, 4).map((text) => (
              <button className="list-card" key={text.id} onClick={() => onOpenText(text)}>
                <div className="list-card-header">
                  <strong>{text.title}</strong>
                  <span className={text.enabled ? "pill success" : "pill"}>{text.enabled ? "Enabled" : "Disabled"}</span>
                </div>
                <p>{excerpt(text.body)}</p>
              </button>
            ))}
            {texts.length === 0 && <EmptyState title="No texts yet" body="Create your first text from the floating form." />}
          </div>
        </section>

        <section className="surface">
          <div className="section-header">
            <div>
              <p className="section-kicker">Recent Polls</p>
              <h3>Performance snapshot</h3>
            </div>
          </div>
          <div className="stack">
            {pollStats.slice(0, 4).map((item) => (
              <button className="list-card" key={item.poll.id} onClick={() => onOpenPoll(item.poll)}>
                <div className="list-card-header">
                  <strong>{item.poll.question}</strong>
                  <span className="pill">{item.total} votes</span>
                </div>
                <p>{item.correct_rate.toFixed(1)}% correct · {item.poll.status}</p>
              </button>
            ))}
            {pollStats.length === 0 && <EmptyState title="No polls yet" body="Generated and manual polls will appear here." />}
          </div>
        </section>
      </div>
    </div>
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

function LearnersPage({
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
        <TextInput
          label="From"
          type="date"
          value={filters.dateFrom}
          onChange={(value) => onFiltersChange((current) => ({ ...current, dateFrom: value }))}
        />
        <TextInput
          label="To"
          type="date"
          value={filters.dateTo}
          onChange={(value) => onFiltersChange((current) => ({ ...current, dateTo: value }))}
        />
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

function LearnerDetailPage({
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
              <strong>
                {item.selected_option_name || "Cleared vote"} · correct answer {item.correct_option}
              </strong>
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
              <p className="subtle">
                Snapshot {formatSnapshotSource(item.recipient_snapshot_source)} · synced {formatWhen(item.recipient_snapshot_synced_at)}
              </p>
            </article>
          ))}
          {detail.missed_polls.length === 0 && (
            <EmptyState title="No missed polls in this filter range" body="This learner responded to every assigned poll in the current scope." />
          )}
        </div>
      </section>
    </section>
  );
}

function TextsPage({
  texts,
  onOpen,
  onCreate,
  onEdit,
  onPreview,
  onSendPoll,
  onDelete,
}: {
  texts: Text[];
  onOpen: (text: Text) => void;
  onCreate: () => void;
  onEdit: (text: Text) => void;
  onPreview: (textId: number) => void;
  onSendPoll: (textId: number) => void;
  onDelete: (text: Text) => void;
}) {
  const [search, setSearch] = useState("");
  const filtered = texts.filter((text) => {
    const needle = search.trim().toLowerCase();
    if (!needle) return true;
    return [text.title, text.body, text.chat_id].some((value) => value.toLowerCase().includes(needle));
  });

  return (
    <section className="resource-page">
      <div className="section-header">
        <div>
          <p className="section-kicker">Texts</p>
          <h2>Manage source content</h2>
        </div>
        <button className="button button-primary" onClick={onCreate}>
          <Plus size={16} /> New text
        </button>
      </div>
      <div className="toolbar">
        <TextInput label="Search" value={search} onChange={setSearch} placeholder="Title, body, or chat ID" />
      </div>
      <div className="resource-grid">
        {filtered.map((text) => (
          <article className="resource-card" key={text.id}>
            <button className="resource-main" onClick={() => onOpen(text)}>
              <div className="resource-topline">
                <span className="resource-id">#{text.id}</span>
                <span className={text.enabled ? "pill success" : "pill"}>{text.enabled ? "Enabled" : "Disabled"}</span>
              </div>
              <h3>{text.title}</h3>
              <p>{excerpt(text.body, 190)}</p>
              <div className="meta-row">
                <span>{text.chat_id || "No chat ID"}</span>
                <span>{text.morning_time} / {text.evening_time}</span>
              </div>
            </button>
            <div className="card-actions">
              <button className="button button-ghost" onClick={() => onEdit(text)}>
                <Pencil size={16} /> Edit
              </button>
              <button className="button button-ghost" onClick={() => onPreview(text.id)}>
                <Play size={16} /> Preview
              </button>
              <button className="button button-secondary" onClick={() => onSendPoll(text.id)}>
                <Send size={16} /> Send poll
              </button>
              <button className="icon-button button-danger" onClick={() => onDelete(text)} title="Delete text">
                <Trash2 size={18} />
              </button>
            </div>
          </article>
        ))}
        {filtered.length === 0 && <EmptyState title="No matching texts" body="Try a different search or create a new text." />}
      </div>
    </section>
  );
}

function TextDetailPage({
  text,
  pool,
  roster,
  onBack,
  onEdit,
  onPreview,
  onSendPoll,
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
          <DetailRow label="Morning" value={text.morning_time} />
          <DetailRow label="Evening" value={text.evening_time} />
          <DetailRow label="AM summary" value={text.summary_time_morning} />
          <DetailRow label="PM summary" value={text.summary_time_evening} />
          <DetailRow
            label="Pool threshold"
            value={
              text.poll_pool_threshold_percent == null
                ? `Inherited ${text.tenant_poll_pool_threshold_percent ?? 80}% used`
                : `${text.poll_pool_threshold_percent}% used`
            }
          />
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
            <RefreshCw size={16} /> Sync roster
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
                <button
                  className="button button-ghost"
                  onClick={() => onMovePoolPoll(poll.id, Math.max(1, (poll.pool_rank || index + 1) - 1))}
                  disabled={index === 0}
                >
                  Up
                </button>
                <button
                  className="button button-ghost"
                  onClick={() => onMovePoolPoll(poll.id, (poll.pool_rank || index + 1) + 1)}
                  disabled={index === pool.items.length - 1}
                >
                  Down
                </button>
                <button className="button button-danger" onClick={() => onDeleteQueuedPoll(poll)}>
                  <Trash2 size={16} /> Delete
                </button>
              </div>
            </article>
          ))}
          {(!pool || pool.items.length === 0) && (
            <EmptyState title="No queued polls" body="Preview or refill to generate the next batch for this text." />
          )}
        </div>
      </section>
    </section>
  );
}

function PollsPage({
  polls,
  texts,
  pollStats,
  onOpen,
  onCreate,
  onEdit,
  onDelete,
}: {
  polls: Poll[];
  texts: Text[];
  pollStats: PollStats[];
  onOpen: (poll: Poll) => void;
  onCreate: () => void;
  onEdit: (poll: Poll) => void;
  onDelete: (poll: Poll) => void;
}) {
  const [search, setSearch] = useState("");
  const textById = new Map(texts.map((item) => [item.id, item]));
  const statsById = new Map(pollStats.map((item) => [item.poll.id, item]));
  const filtered = polls.filter((poll) => {
    const needle = search.trim().toLowerCase();
    if (!needle) return true;
    return [poll.question, poll.status, poll.chat_id].some((value) => value.toLowerCase().includes(needle));
  });

  return (
    <section className="resource-page">
      <div className="section-header">
        <div>
          <p className="section-kicker">Polls</p>
          <h2>Track delivery and answers</h2>
        </div>
        <button className="button button-primary" onClick={onCreate}>
          <Plus size={16} /> New poll
        </button>
      </div>
      <div className="toolbar">
        <TextInput label="Search" value={search} onChange={setSearch} placeholder="Question, status, or chat ID" />
      </div>
      <div className="resource-grid">
        {filtered.map((poll) => {
          const stats = statsById.get(poll.id);
          const sourceText = textById.get(poll.text_id);
          return (
            <article className="resource-card" key={poll.id}>
              <button className="resource-main" onClick={() => onOpen(poll)}>
                <div className="resource-topline">
                  <span className="resource-id">#{poll.id}</span>
                  <span className={poll.status === "queued" ? "pill success" : "pill"}>{poll.status}</span>
                </div>
                <h3>{poll.question}</h3>
                <p>{sourceText ? excerpt(sourceText.body, 120) : "No linked text loaded."}</p>
                <div className="meta-row">
                  <span>{stats ? `${stats.total} votes` : "0 votes"}</span>
                  <span>{stats ? `${stats.correct_rate.toFixed(1)}% correct` : "No stats yet"}</span>
                </div>
                <div className="meta-row">
                  <span>{poll.status === "queued" ? `Queue rank ${poll.pool_rank ?? "?"}` : poll.manual_lock ? "Locked" : "Open"}</span>
                  <span>Changes {minutesLabel(poll.change_window_seconds)}</span>
                </div>
              </button>
              <div className="option-badges">
                {poll.options.map((option) => (
                  <span className={option === poll.correct_option ? "pill success" : "pill"} key={option}>
                    {option}
                  </span>
                ))}
              </div>
              <div className="card-actions">
                <button className="button button-ghost" onClick={() => onEdit(poll)}>
                  <Pencil size={16} /> Edit
                </button>
                <button className="icon-button button-danger" onClick={() => onDelete(poll)} title="Delete poll">
                  <Trash2 size={18} />
                </button>
              </div>
            </article>
          );
        })}
        {filtered.length === 0 && <EmptyState title="No matching polls" body="Try a different search or create a new poll." />}
      </div>
    </section>
  );
}

function PollDetailPage({
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
            <StatBlock label="Vote changes" value={minutesLabel(poll.change_window_seconds)} />
            <StatBlock label="Poll lock" value={poll.manual_lock ? "Locked" : "Open"} />
            <StatBlock label="Auto-lock" value={minutesLabel(poll.auto_lock_seconds)} />
          </div>
          <div className="prose-block subtle">{poll.explanation || "No explanation provided."}</div>
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
              ? `Snapshot ${formatSnapshotSource(coverage?.recipient_snapshot_source)} · synced ${formatWhen(
                  coverage?.recipient_snapshot_synced_at,
                )}`
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
              <EmptyState
                title="No missed responses"
                body={
                  coverage?.coverage_available
                    ? "Everyone assigned to this poll has responded."
                    : "Coverage tracking was unavailable for this poll."
                }
              />
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
                      <td>
                        {item.latest_ignored_option_name
                          ? `${item.latest_ignored_option_name} (${describeIgnoredReason(item.latest_ignored_reason)})`
                          : "—"}
                      </td>
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

function DocPage({ onOpenSwagger }: { onOpenSwagger: () => void }) {
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
            <DocItem title="Webhooks" body="GreenAPI callbacks post to /webhooks/greenapi/{tenant_id}; unmatched poll updates are logged and ignored." />
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
          <p className="subtle">
            JSON logs and human-readable logs are written locally by default with request IDs and secret redaction.
          </p>
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

function DocItem({ title, body }: { title: string; body: string }) {
  return (
    <article className="doc-item">
      <strong>{title}</strong>
      <p>{body}</p>
    </article>
  );
}

function SettingsPage({ tenant, onEdit }: { tenant: Tenant; onEdit: () => void }) {
  const readiness = [
    { label: "GreenAPI URL", ready: Boolean(tenant.greenapi_api_url) },
    { label: "GreenAPI instance", ready: Boolean(tenant.greenapi_id_instance) },
    { label: "GreenAPI token", ready: Boolean(tenant.greenapi_api_token_instance) },
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
          <DetailRow label="GreenAPI URL" value={tenant.greenapi_api_url} />
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

function TextModal({
  tenant,
  initialText,
  onClose,
  onSaved,
  onError,
}: {
  tenant: Tenant;
  initialText?: Text;
  onClose: () => void;
  onSaved: (message: string) => void;
  onError: (message: string) => void;
}) {
  const editing = Boolean(initialText);
  const [form, setForm] = useState<TextFormState>(initialText ? textToForm(initialText) : blankText(tenant.id));
  const [attachment, setAttachment] = useState<File | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    try {
      if (editing && initialText) {
        await api<Text>(`/texts/${initialText.id}`, { method: "PATCH", body: JSON.stringify(form) });
        onSaved("Text updated");
        return;
      }
      const data = new FormData();
      data.set("tenant_id", String(tenant.id));
      data.set("title", form.title);
      data.set("body", form.body);
      data.set("chat_id", form.chat_id);
      data.set("morning_time", form.morning_time);
      data.set("evening_time", form.evening_time);
      data.set("summary_time_morning", form.summary_time_morning);
      data.set("summary_time_evening", form.summary_time_evening);
      if (form.poll_pool_threshold_percent != null) data.set("poll_pool_threshold_percent", String(form.poll_pool_threshold_percent));
      data.set("enabled", String(form.enabled));
      if (attachment) data.set("attachment", attachment);
      await api<Text>("/texts", { method: "POST", body: data });
      onSaved("Text created");
    } catch (err) {
      onError(err instanceof Error ? err.message : "Failed to save text");
    }
  }

  return (
    <Modal title={editing ? "Edit Text" : "Create Text"} onClose={onClose}>
      <form className="modal-form" onSubmit={submit}>
        <TextInput label="Title" value={form.title} onChange={(value) => setForm({ ...form, title: value })} />
        <label>
          Body
          <textarea rows={8} value={form.body} onChange={(event) => setForm({ ...form, body: event.target.value })} />
        </label>
        <TextInput label="WhatsApp group chat ID" value={form.chat_id} onChange={(value) => setForm({ ...form, chat_id: value })} />
        <div className="time-grid">
          <TextInput label="Morning" value={form.morning_time} onChange={(value) => setForm({ ...form, morning_time: value })} />
          <TextInput label="Evening" value={form.evening_time} onChange={(value) => setForm({ ...form, evening_time: value })} />
          <TextInput
            label="AM summary"
            value={form.summary_time_morning}
            onChange={(value) => setForm({ ...form, summary_time_morning: value })}
          />
          <TextInput
            label="PM summary"
            value={form.summary_time_evening}
            onChange={(value) => setForm({ ...form, summary_time_evening: value })}
          />
        </div>
        <TextInput
          label="Pool threshold percent used"
          type="number"
          value={form.poll_pool_threshold_percent == null ? "" : String(form.poll_pool_threshold_percent)}
          placeholder={`Blank = inherit ${tenant.poll_pool_threshold_percent}%`}
          onChange={(value) =>
            setForm({
              ...form,
              poll_pool_threshold_percent: value.trim() ? Math.max(0, Math.min(100, Number(value))) : null,
            })
          }
        />
        <label className="check">
          <input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} />
          Enable text
        </label>
        {!editing && (
          <label>
            Attachment
            <input type="file" onChange={(event) => setAttachment(event.target.files?.[0] || null)} />
          </label>
        )}
        <div className="modal-actions">
          <button className="button button-ghost" type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="button button-primary" type="submit">
            <Save size={16} /> {editing ? "Save changes" : "Create text"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function PollModal({
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
        <TextInput label="Scheduled slot" value={form.scheduled_slot || ""} onChange={(value) => setForm({ ...form, scheduled_slot: value })} />
        <div className="time-grid">
          <TextInput
            label="Change window minutes"
            type="number"
            value={form.change_window_seconds == null ? "" : String(form.change_window_seconds / 60)}
            placeholder="Blank = no limit"
            onChange={(value) =>
              setForm({
                ...form,
                change_window_seconds: value.trim() ? Math.max(0, Number(value) * 60) : null,
              })
            }
          />
          <TextInput
            label="Auto-lock minutes"
            type="number"
            value={form.auto_lock_seconds == null ? "" : String(form.auto_lock_seconds / 60)}
            placeholder="Blank = disabled"
            onChange={(value) =>
              setForm({
                ...form,
                auto_lock_seconds: value.trim() ? Math.max(0, Number(value) * 60) : null,
              })
            }
          />
        </div>
        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={form.manual_lock}
            onChange={(event) => setForm({ ...form, manual_lock: event.target.checked })}
          />
          <span>Lock poll manually</span>
        </label>
        <label>
          Explanation
          <textarea rows={4} value={form.explanation} onChange={(event) => setForm({ ...form, explanation: event.target.value })} />
        </label>
        <label>
          Generated from text
          <textarea rows={5} value={form.generated_from_text} onChange={(event) => setForm({ ...form, generated_from_text: event.target.value })} />
        </label>
        <div className="modal-actions">
          <button className="button button-ghost" type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="button button-primary" type="submit">
            <Save size={16} /> {editing ? "Save changes" : "Create poll"}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function SettingsModal({
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
      await api<Tenant>(`/tenants/${tenant.id}`, { method: "PATCH", body: JSON.stringify(form) });
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
        <TextInput
          label="Password"
          type="password"
          value={form.password}
          placeholder="Leave blank to keep current password"
          onChange={(value) => setForm({ ...form, password: value })}
        />
        <TextInput
          label="Pool threshold percent used"
          type="number"
          value={String(form.poll_pool_threshold_percent)}
          onChange={(value) =>
            setForm({
              ...form,
              poll_pool_threshold_percent: Math.max(0, Math.min(100, Number(value || 0))),
            })
          }
        />
        <TextInput label="GreenAPI URL" value={form.greenapi_api_url} onChange={(value) => setForm({ ...form, greenapi_api_url: value })} />
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
        <TextInput label="Gemini API key" type="password" value={form.gemini_api_key} onChange={(value) => setForm({ ...form, gemini_api_key: value })} />
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
        <div className="modal-actions">
          <button className="button button-ghost" type="button" onClick={onClose}>
            Cancel
          </button>
          <button className="button button-primary" type="submit">
            <Save size={16} /> Save workspace
          </button>
        </div>
      </form>
    </Modal>
  );
}

function PreviewModal({ preview, onClose }: { preview: GeneratedQuestion; onClose: () => void }) {
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

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: React.ReactNode }) {
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card" onClick={(event) => event.stopPropagation()}>
        <div className="modal-header">
          <h3>{title}</h3>
          <button className="icon-button button-ghost" onClick={onClose} title="Close">
            <X size={18} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function EmptyState({ title, body }: { title: string; body: string }) {
  return (
    <div className="empty-state">
      <h3>{title}</h3>
      <p>{body}</p>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function StatBlock({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="stat-block">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function TextInput({
  label,
  value,
  onChange,
  name,
  type = "text",
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  name?: string;
  type?: string;
  placeholder?: string;
}) {
  return (
    <label>
      {label}
      <input
        name={name}
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}
