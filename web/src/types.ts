export type Tenant = {
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

export type ScheduleRule = {
  id?: number;
  tenant_id?: number;
  text_id?: number;
  name?: string | null;
  delivery_type: "poll" | "summary";
  rule_type: "daily_time" | "weekday_time" | "month_date_time" | "random_window";
  enabled: boolean;
  time?: string | null;
  weekdays?: number[];
  month_dates?: number[];
  window_start?: string | null;
  window_end?: string | null;
  count_mode: "fixed" | "range";
  count_value?: number | null;
  count_min?: number | null;
  count_max?: number | null;
  label?: string | null;
};

export type Text = {
  id: number;
  tenant_id: number;
  tenant_name: string;
  title: string;
  body: string;
  chat_id: string;
  poll_pool_threshold_percent?: number | null;
  tenant_poll_pool_threshold_percent?: number;
  enabled: boolean;
  attachment_name?: string | null;
  schedule_rules: ScheduleRule[];
};

export type GroupChat = {
  chat_id: string;
  name: string;
  policy: "allow" | "neutral" | "block";
  last_synced_at?: string | null;
  created_at?: string;
  updated_at?: string;
};

export type Poll = {
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

export type PollPool = {
  text_id: number;
  queued_count: number;
  effective_threshold_percent: number;
  refill_when_below: number;
  target_size: number;
  refill_batch_size: number;
  next_poll?: Poll | null;
  items: Poll[];
};

export type PollStats = {
  poll: Poll;
  options: string[];
  counts: Record<string, number>;
  total: number;
  correct_count: number;
  correct_rate: number;
};

export type VoteEvent = {
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

export type VoteStatus = {
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

export type Page<T> = {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  has_next: boolean;
};

export type LearnerSummary = {
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

export type LearnerHistoryItem = {
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

export type LearnerMissedPollItem = {
  poll_id: number;
  text_id: number;
  question: string;
  sent_at?: string | null;
  recipient_snapshot_source?: string | null;
  recipient_snapshot_synced_at?: string | null;
};

export type LearnerDetail = {
  learner: LearnerSummary;
  history: LearnerHistoryItem[];
  missed_polls: LearnerMissedPollItem[];
};

export type RosterMember = {
  voter_wid: string;
  display_name: string;
  phone_number: string;
  is_active_in_chat: boolean;
  excluded_from_coverage: boolean;
  last_synced_at?: string | null;
};

export type TextRoster = {
  text_id: number;
  chat_id: string;
  last_synced_at?: string | null;
  active_count: number;
  excluded_count: number;
  items: RosterMember[];
};

export type PollCoverageItem = {
  voter_wid: string;
  display_name: string;
  phone_number: string;
  assigned_at?: string | null;
};

export type PollCoverage = {
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

export type GeneratedQuestion = {
  question: string;
  options: string[];
  correct_option: string;
  explanation: string;
};

export type DocsSession = {
  docs_token: string;
  token_type: string;
  expires_at: string;
  docs_url: string;
  openapi_url: string;
};

export type Toast = { kind: "success" | "error"; message: string } | null;

export type TextFormState = {
  tenant_id: number;
  title: string;
  body: string;
  chat_id: string;
  poll_pool_threshold_percent?: number | null;
  enabled: boolean;
  assigned_rule_ids: number[];
  new_rules: ScheduleRule[];
};

export type PollFormState = Omit<Poll, "id" | "created_at">;
export type TenantFormState = Omit<Tenant, "id"> & { password: string };
export type RegisterFormState = { name: string; username: string; password: string; confirmPassword: string; timezone: string };

export type LearnerFilters = {
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

export type PollFilters = {
  status: "" | "draft" | "queued" | "sent";
  textId: string;
  dateFrom: string;
  dateTo: string;
};

export type Route =
  | { name: "login" }
  | { name: "register" }
  | { name: "dashboard" }
  | { name: "learners" }
  | { name: "learner-detail"; voterWid: string }
  | { name: "chats" }
  | { name: "texts" }
  | { name: "text-detail"; id: number }
  | { name: "rules" }
  | { name: "polls" }
  | { name: "poll-detail"; id: number }
  | { name: "doc" }
  | { name: "settings" };

export const defaultTenantForm: TenantFormState = {
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
