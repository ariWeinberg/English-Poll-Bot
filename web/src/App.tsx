import React, { FormEvent, useEffect, useMemo, useState } from "react";
import {
  BarChart3,
  BellRing,
  BookOpen,
  Building2,
  CheckCircle2,
  Download,
  FileText,
  LogOut,
  Menu,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Send,
  Settings,
  Sparkles,
  Trash2,
  Users,
  Vote,
  X,
} from "lucide-react";
import { EmptyState, TextInput } from "./components/common";
import { PollModal, PreviewModal, ScheduleRuleModal, SettingsModal, TextModal } from "./components/modals";
import { api, downloadCsv, getToken, setToken } from "./lib/api";
import { chatPolicyLabel, excerpt, formatWhen, minutesLabel, scheduleSummary } from "./lib/format";
import { navigateTo, parseRoute } from "./lib/routes";
import { DocPage } from "./pages/DocPage";
import { LearnerDetailPage } from "./pages/LearnerDetailPage";
import { LearnersPage } from "./pages/LearnersPage";
import { PollDetailPage } from "./pages/PollDetailPage";
import { SettingsPage } from "./pages/SettingsPage";
import { TextDetailPage } from "./pages/TextDetailPage";
import {
  defaultTenantForm,
  type DocsSession,
  type GeneratedQuestion,
  type GroupChat,
  type LearnerFilters,
  type Page,
  type Poll,
  type PollPool,
  type PollStats,
  type Route,
  type RosterMember,
  type ScheduleRule,
  type Tenant,
  type Text,
  type TextRoster,
  type Toast,
  type VoteEvent,
  type VoteStatus,
  type RegisterFormState,
} from "./types";

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
        <TextInput label="Password" type="password" value={form.password} onChange={(value) => setForm({ ...form, password: value })} />
        <TextInput label="Confirm password" type="password" value={form.confirmPassword} onChange={(value) => setForm({ ...form, confirmPassword: value })} />
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
  const [groupChats, setGroupChats] = useState<GroupChat[]>([]);
  const [texts, setTexts] = useState<Text[]>([]);
  const [scheduleRules, setScheduleRules] = useState<ScheduleRule[]>([]);
  const [polls, setPolls] = useState<Poll[]>([]);
  const [pollStats, setPollStats] = useState<PollStats[]>([]);
  const [voteEvents, setVoteEvents] = useState<VoteEvent[]>([]);
  const [currentVoteStatus, setCurrentVoteStatus] = useState<VoteStatus[]>([]);
  const [loading, setLoading] = useState(true);
  const [toast, setToast] = useState<Toast>(null);
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [textModal, setTextModal] = useState<{ mode: "create" | "edit"; text?: Text } | null>(null);
  const [ruleModal, setRuleModal] = useState<{ mode: "create" | "edit"; rule?: ScheduleRule } | null>(null);
  const [pollModal, setPollModal] = useState<{ mode: "create" | "edit"; poll?: Poll } | null>(null);
  const [settingsModalOpen, setSettingsModalOpen] = useState(false);
  const [preview, setPreview] = useState<GeneratedQuestion | null>(null);
  const [currentPool, setCurrentPool] = useState<PollPool | null>(null);
  const [currentRoster, setCurrentRoster] = useState<TextRoster | null>(null);
  const [currentCoverage, setCurrentCoverage] = useState<any>(null);
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
      const [chatList, textPage, ruleList, pollPage, stats, votePage, pool] = await Promise.all([
        api<GroupChat[]>("/chats"),
        api<Page<Text>>(`/texts?tenant_id=${me.id}&page_size=100`),
        api<ScheduleRule[]>("/schedule-rules"),
        api<Page<Poll>>(`/polls?tenant_id=${me.id}&page_size=100`),
        api<PollStats[]>(`/polls/stats?tenant_id=${me.id}&limit=100`),
        api<Page<VoteEvent>>(`/poll-vote-events?tenant_id=${me.id}&page_size=200`),
        route.name === "text-detail" ? api<PollPool>(`/texts/${route.id}/poll-pool`) : Promise.resolve(null),
      ]);
      const [roster, coverage] = await Promise.all([
        route.name === "text-detail" ? api<TextRoster>(`/texts/${route.id}/roster`) : Promise.resolve(null),
        route.name === "poll-detail" ? api(`/polls/${route.id}/coverage?page_size=50`) : Promise.resolve(null),
      ]);
      setTenant(me);
      setGroupChats(chatList);
      setTexts(textPage.items);
      setScheduleRules(ruleList);
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
    () => Boolean(tenant?.greenapi_api_url && tenant.greenapi_id_instance && tenant.greenapi_api_token_instance && tenant.gemini_api_key),
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

  async function handleRefreshChats() {
    try {
      const chats = await api<GroupChat[]>("/chats/refresh", { method: "POST" });
      setGroupChats(chats);
      handleSuccess("Chats refreshed");
    } catch (err) {
      handleError(err instanceof Error ? err.message : "Chat refresh failed");
    }
  }

  async function handleUpdateChatPolicy(chatId: string, policy: GroupChat["policy"]) {
    try {
      await api<GroupChat>(`/chats/${encodeURIComponent(chatId)}/policy`, {
        method: "PATCH",
        body: JSON.stringify({ policy }),
      });
      handleSuccess(`Chat moved to ${chatPolicyLabel(policy).toLowerCase()}`);
    } catch (err) {
      handleError(err instanceof Error ? err.message : "Failed to update chat policy");
    }
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
            <LearnerDetailPage tenant={tenant} texts={texts} voterWid={route.voterWid} filters={learnerFilters} onBack={() => navigateTo({ name: "learners" })} />
          )}
          {route.name === "chats" && <ChatsPage chats={groupChats} onRefresh={handleRefreshChats} onSetPolicy={handleUpdateChatPolicy} />}
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
          {route.name === "rules" && (
            <RulesPage
              rules={scheduleRules}
              onCreate={() => setRuleModal({ mode: "create" })}
              onEdit={(rule) => setRuleModal({ mode: "edit", rule })}
              onDelete={async (rule) => {
                if (!window.confirm("Delete this shared rule?")) return;
                try {
                  await api(`/schedule-rules/${rule.id}`, { method: "DELETE" });
                  handleSuccess("Rule deleted");
                } catch (err) {
                  handleError(err instanceof Error ? err.message : "Failed to delete rule");
                }
              }}
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
          {route.name === "settings" && <SettingsPage tenant={tenant} onEdit={() => setSettingsModalOpen(true)} />}
          {route.name === "doc" && <DocPage onOpenSwagger={() => void handleOpenSwagger()} />}
        </div>
      </div>

      {textModal && (
        <TextModal
          tenant={tenant}
          initialText={textModal.text}
          availableChats={groupChats}
          availableRules={scheduleRules}
          onClose={() => setTextModal(null)}
          onSaved={(message) => {
            setTextModal(null);
            handleSuccess(message);
          }}
          onError={handleError}
        />
      )}
      {ruleModal && (
        <ScheduleRuleModal
          initialRule={ruleModal.rule}
          onClose={() => setRuleModal(null)}
          onSaved={(message) => {
            setRuleModal(null);
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

function Sidebar({ route, open, tenant, onClose }: { route: Route; open: boolean; tenant: Tenant; onClose: () => void }) {
  const items = [
    { icon: <BarChart3 size={18} />, label: "Dashboard", route: { name: "dashboard" } as Route, active: route.name === "dashboard" },
    { icon: <Users size={18} />, label: "Learners", route: { name: "learners" } as Route, active: route.name === "learners" || route.name === "learner-detail" },
    { icon: <Building2 size={18} />, label: "Chats", route: { name: "chats" } as Route, active: route.name === "chats" },
    { icon: <FileText size={18} />, label: "Texts", route: { name: "texts" } as Route, active: route.name === "texts" || route.name === "text-detail" },
    { icon: <BellRing size={18} />, label: "Rules", route: { name: "rules" } as Route, active: route.name === "rules" },
    { icon: <Vote size={18} />, label: "Polls", route: { name: "polls" } as Route, active: route.name === "polls" || route.name === "poll-detail" },
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
            <button className={item.active ? "sidebar-link active" : "sidebar-link"} key={item.label} onClick={() => navigateTo(item.route)}>
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
    case "chats":
      return "Group Chats";
    case "texts":
      return "Texts";
    case "text-detail":
      return "Text Detail";
    case "rules":
      return "Reusable Rules";
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
                <span>{scheduleSummary(text)}</span>
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

function ChatsPage({
  chats,
  onRefresh,
  onSetPolicy,
}: {
  chats: GroupChat[];
  onRefresh: () => void;
  onSetPolicy: (chatId: string, policy: GroupChat["policy"]) => void;
}) {
  const [search, setSearch] = useState("");
  const filtered = chats.filter((chat) => {
    const needle = search.trim().toLowerCase();
    if (!needle) return true;
    return [chat.name, chat.chat_id, chatPolicyLabel(chat.policy)].some((value) => value.toLowerCase().includes(needle));
  });

  return (
    <section className="resource-page">
      <div className="section-header">
        <div>
          <p className="section-kicker">Chats</p>
          <h2>Chat Allowlist / Blocklist</h2>
        </div>
        <button className="button button-primary" onClick={onRefresh}>
          <RefreshCw size={16} /> Refresh chats
        </button>
      </div>
      <div className="toolbar">
        <TextInput label="Search chats" value={search} onChange={setSearch} placeholder="Group name or chat ID" />
      </div>
      <div className="resource-grid">
        {filtered.map((chat) => (
          <article className="resource-card" key={chat.chat_id}>
            <div className="resource-main">
              <div className="resource-topline">
                <span className="resource-id">{chat.chat_id}</span>
                <span className={chat.policy === "allow" ? "pill success" : "pill"}>{chatPolicyLabel(chat.policy)}</span>
              </div>
              <h3>{chat.name}</h3>
              <p>Last synced {formatWhen(chat.last_synced_at)}</p>
            </div>
            <div className="card-actions">
              <button className="button button-ghost" onClick={() => onSetPolicy(chat.chat_id, "allow")}>Allow</button>
              <button className="button button-ghost" onClick={() => onSetPolicy(chat.chat_id, "neutral")}>Neutral</button>
              <button className="button button-danger" onClick={() => onSetPolicy(chat.chat_id, "block")}>Block</button>
            </div>
          </article>
        ))}
        {filtered.length === 0 && <EmptyState title="No chats loaded" body="Refresh group chats from GreenAPI, then manage the allowlist and blocklist here." />}
      </div>
    </section>
  );
}

function RulesPage({
  rules,
  onCreate,
  onEdit,
  onDelete,
}: {
  rules: ScheduleRule[];
  onCreate: () => void;
  onEdit: (rule: ScheduleRule) => void;
  onDelete: (rule: ScheduleRule) => void;
}) {
  const [search, setSearch] = useState("");
  const filtered = rules.filter((rule) => {
    const needle = search.trim().toLowerCase();
    if (!needle) return true;
    return [rule.name || "", rule.label || "", scheduleSummary({ schedule_rules: [rule] } as Text)].some((value) => value.toLowerCase().includes(needle));
  });

  return (
    <section className="resource-page">
      <div className="section-header">
        <div>
          <p className="section-kicker">Rules</p>
          <h2>Reusable Rules</h2>
        </div>
        <button className="button button-primary" onClick={onCreate}>
          <Plus size={16} /> New rule
        </button>
      </div>
      <div className="toolbar">
        <TextInput label="Search rules" value={search} onChange={setSearch} placeholder="Name, label, or timing" />
      </div>
      <div className="resource-grid">
        {filtered.map((rule) => (
          <article className="resource-card" key={rule.id}>
            <div className="resource-main">
              <div className="resource-topline">
                <span className="resource-id">#{rule.id}</span>
                <span className={rule.enabled ? "pill success" : "pill"}>{rule.enabled ? "Enabled" : "Disabled"}</span>
              </div>
              <h3>{rule.name || "Untitled rule"}</h3>
              <p>{scheduleSummary({ schedule_rules: [rule] } as Text)}</p>
            </div>
            <div className="card-actions">
              <button className="button button-ghost" onClick={() => onEdit(rule)}>
                <Pencil size={16} /> Edit
              </button>
              <button className="icon-button button-danger" onClick={() => onDelete(rule)} title="Delete rule">
                <Trash2 size={18} />
              </button>
            </div>
          </article>
        ))}
        {filtered.length === 0 && <EmptyState title="No matching rules" body="Create a reusable rule or adjust the search." />}
      </div>
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
