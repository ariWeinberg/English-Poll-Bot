import type { Poll, PollFormState, ScheduleRule, Tenant, TenantFormState, Text, TextFormState } from "../types";

export function blankText(tenantId: number): TextFormState {
  return {
    tenant_id: tenantId,
    title: "",
    body: "",
    chat_id: "",
    poll_pool_threshold_percent: null,
    enabled: true,
    assigned_rule_ids: [],
    new_rules: [],
  };
}

export function blankPoll(tenantId: number, text?: Text): PollFormState {
  return {
    tenant_id: tenantId,
    text_id: text?.id || 0,
    question: "",
    options: ["A", "B", "C", "D"],
    correct_option: "A",
    explanation: "",
    provider: null,
    provider_message_id: "",
    greenapi_message_id: "",
    chat_id: text?.chat_id || "",
    generated_from_text: text?.body || "",
    status: "draft",
    review_status: "draft",
    review_notes: "",
    scheduled_slot: "",
    sent_at: "",
    summary_sent_at: "",
    change_window_seconds: null,
    manual_lock: false,
    auto_lock_seconds: null,
  };
}

export function tenantToForm(tenant: Tenant): TenantFormState {
  const { id: _id, ...rest } = tenant;
  const connectorConfig = tenant.whatsapp_connector?.config || {};
  return {
    ...rest,
    whatsapp_provider: tenant.whatsapp_provider,
    whatsapp_connector: {
      ...tenant.whatsapp_connector,
      config: {
        api_url: connectorConfig.api_url || tenant.greenapi_api_url || "",
        id_instance: connectorConfig.id_instance || tenant.greenapi_id_instance || "",
        api_token_instance: connectorConfig.api_token_instance || tenant.greenapi_api_token_instance || "",
        base_url: connectorConfig.base_url || "",
        session: connectorConfig.session || "",
        api_key: connectorConfig.api_key || "",
      },
    },
    password: "",
  };
}

export function textToForm(text: Text): TextFormState {
  return {
    tenant_id: text.tenant_id,
    title: text.title,
    body: text.body,
    chat_id: text.chat_id,
    poll_pool_threshold_percent: text.poll_pool_threshold_percent ?? null,
    enabled: text.enabled,
    assigned_rule_ids: text.schedule_rules.map((rule) => rule.id || 0).filter((ruleId) => ruleId > 0),
    new_rules: [],
  };
}

export function blankScheduleRule(deliveryType: "poll" | "summary" = "poll"): ScheduleRule {
  return {
    delivery_type: deliveryType,
    rule_type: "daily_time",
    enabled: true,
    time: deliveryType === "summary" ? "08:29" : "08:30",
    weekdays: [0, 1, 2, 3, 4],
    month_dates: [1],
    window_start: "08:00",
    window_end: "09:00",
    count_mode: "fixed",
    count_value: 1,
    count_min: 1,
    count_max: 2,
    label: "",
  };
}

export function pollToForm(poll: Poll): PollFormState {
  return {
    tenant_id: poll.tenant_id,
    text_id: poll.text_id,
    question: poll.question,
    options: poll.options,
    correct_option: poll.correct_option,
    explanation: poll.explanation,
    provider: poll.provider || null,
    provider_message_id: poll.provider_message_id || "",
    greenapi_message_id: poll.greenapi_message_id || "",
    chat_id: poll.chat_id,
    generated_from_text: poll.generated_from_text,
    status: poll.status,
    review_status: poll.review_status,
    review_notes: poll.review_notes,
    scheduled_slot: poll.scheduled_slot || "",
    sent_at: poll.sent_at || "",
    summary_sent_at: poll.summary_sent_at || "",
    pool_rank: poll.pool_rank ?? null,
    change_window_seconds: poll.change_window_seconds ?? null,
    manual_lock: poll.manual_lock,
    auto_lock_seconds: poll.auto_lock_seconds ?? null,
  };
}
