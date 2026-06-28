import type {
  GroupChat,
  LearnerFilters,
  ScheduleRule,
  Text,
  VoteEvent,
} from "../types";
import { blankScheduleRule } from "./forms";

export function describeVoteEvent(event: VoteEvent) {
  const suffix = event.accepted ? "" : ` (ignored: ${describeIgnoredReason(event.ignored_reason)})`;
  if (event.event_type === "unvote") {
    return `retracted vote from ${event.previous_option_name || "unknown option"}${suffix}`;
  }
  if (event.event_type === "change") {
    return `changed ${event.previous_option_name || "unknown option"} -> ${event.option_name}${suffix}`;
  }
  return `voted ${event.option_name}${suffix}`;
}

export function formatVoteContact(contact: { voter_name?: string | null; phone_number?: string | null; voter_wid: string }) {
  const name = contact.voter_name?.trim();
  const phone = contact.phone_number?.trim();
  if (name && phone) return `${name} (${phone})`;
  if (name) return name;
  if (phone) return phone;
  return contact.voter_wid;
}

export function describeIgnoredReason(reason?: string | null) {
  if (reason === "manual_lock") return "poll locked";
  if (reason === "auto_lock_expired") return "auto-lock expired";
  if (reason === "change_window_expired") return "change window expired";
  return "rule blocked";
}

export function chatPolicyLabel(policy: GroupChat["policy"]) {
  if (policy === "allow") return "Allowlist";
  if (policy === "block") return "Blocklist";
  return "Neutral";
}

export function minutesLabel(seconds?: number | null) {
  if (seconds == null) return "No limit";
  return `${Math.floor(seconds / 60)} min`;
}

export function excerpt(value: string, length = 160) {
  if (value.length <= length) return value;
  return `${value.slice(0, length)}...`;
}

export function formatWhen(value?: string | null) {
  return value || "Not sent yet";
}

export function formatActivity(value?: string | null) {
  return value || "—";
}

export function formatSnapshotSource(value?: string | null) {
  if (value === "live_sync") return "Live sync";
  if (value === "cached_roster") return "Cached roster";
  if (value === "unavailable") return "Unavailable";
  return value || "Unavailable";
}

export const WEEKDAY_OPTIONS = [
  { value: 0, label: "Mon" },
  { value: 1, label: "Tue" },
  { value: 2, label: "Wed" },
  { value: 3, label: "Thu" },
  { value: 4, label: "Fri" },
  { value: 5, label: "Sat" },
  { value: 6, label: "Sun" },
];

function ruleCountLabel(rule: ScheduleRule) {
  if (rule.count_mode === "range") return `${rule.count_min ?? 1}-${rule.count_max ?? 1}x`;
  return `${rule.count_value ?? 1}x`;
}

export function describeRule(rule: ScheduleRule) {
  const name = rule.name?.trim();
  const prefix = `${rule.delivery_type === "summary" ? "Summary" : "Poll"} ${rule.enabled ? "" : "(disabled) "}`.trim();
  const countText = rule.delivery_type === "poll" ? ` • ${ruleCountLabel(rule)}` : "";
  const label = rule.label?.trim();
  const titlePrefix = name || label ? `${name || label}: ` : "";
  if (rule.rule_type === "daily_time") return `${titlePrefix}${prefix} daily at ${rule.time}${countText}`;
  if (rule.rule_type === "weekday_time") {
    const days = (rule.weekdays || []).map((day) => WEEKDAY_OPTIONS.find((item) => item.value === day)?.label || String(day)).join(", ");
    return `${titlePrefix}${prefix} on ${days} at ${rule.time}${countText}`;
  }
  if (rule.rule_type === "month_date_time") {
    return `${titlePrefix}${prefix} on days ${(rule.month_dates || []).join(", ")} at ${rule.time}${countText}`;
  }
  return `${titlePrefix}${prefix} random ${rule.window_start}-${rule.window_end}${countText}`;
}

export function scheduleSummary(text: Text) {
  const rules = text.schedule_rules || [];
  const pollRules = rules.filter((rule) => rule.delivery_type === "poll" && rule.enabled);
  if (pollRules.length === 0) return "Manual only";
  return pollRules.map(describeRule).join(" | ");
}

function shiftMinuteEarlier(value: string) {
  const [hoursText, minutesText] = value.split(":");
  const hours = Number(hoursText);
  const minutes = Number(minutesText);
  const total = Math.max(0, hours * 60 + minutes - 1);
  const nextHours = String(Math.floor(total / 60)).padStart(2, "0");
  const nextMinutes = String(total % 60).padStart(2, "0");
  return `${nextHours}:${nextMinutes}`;
}

export function autoSummaryRuleFor(rule: ScheduleRule): ScheduleRule {
  if (rule.rule_type === "random_window") {
    const nextStart = rule.window_start ? shiftMinuteEarlier(rule.window_start) : "00:00";
    const nextEnd = rule.window_end ? shiftMinuteEarlier(rule.window_end) : "00:01";
    return {
      ...blankScheduleRule("summary"),
      delivery_type: "summary",
      rule_type: "random_window",
      enabled: rule.enabled,
      window_start: nextStart,
      window_end: nextEnd > nextStart ? nextEnd : rule.window_end || "00:01",
      label: rule.label ? `${rule.label} summary` : "Auto summary",
    };
  }
  return {
    ...blankScheduleRule("summary"),
    delivery_type: "summary",
    rule_type: rule.rule_type,
    enabled: rule.enabled,
    time: rule.time ? shiftMinuteEarlier(rule.time) : "00:00",
    weekdays: [...(rule.weekdays || [])],
    month_dates: [...(rule.month_dates || [])],
    label: rule.label ? `${rule.label} summary` : "Auto summary",
  };
}

export function learnerQueryString(tenantId: number, filters: LearnerFilters, extra?: Record<string, string | number | undefined>) {
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
