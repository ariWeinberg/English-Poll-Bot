# Operations Runbook

## Access

- App users authenticate through `/api/v1/auth/login`.
- Public Swagger and OpenAPI are disabled at `/docs` and `/openapi.json`.
- Logged-in users can open the in-app `/doc` page and mint a short-lived Swagger session through `POST /api/v1/docs/session`.
- The protected docs endpoints are `/api/v1/docs?token=...` and `/api/v1/openapi.json?token=...`.

## Local Logging

The API writes local logs with secret redaction by default:

- `LOG_LEVEL`: standard Python log level, default `INFO`.
- `LOG_FORMAT`: `human` or `json` for stdout fallback, default `human`.
- `LOG_FILE`: JSON-lines file, default `logs/app.jsonl`.
- `LOG_HUMAN_FILE`: readable log file, default `logs/app.log`.
- `LOG_REQUEST_BODY_ENABLED`: log redacted JSON request bodies when set to `true`, default `false`.
- `SCHEDULER_DEBUG_ENABLED`: worker-only ultra-verbose scheduler tracing when set to `true`, default `false`.

Logged events include request start/finish with request IDs, scheduler ticks, skipped scheduler work, per-slot send attempts, pool refills, summary sends, webhook decisions, and exceptions.

## Scheduler

The dedicated `scheduler` worker runs every minute in UTC and evaluates recurring rules in each tenant's local timezone. Rule times stay stored as tenant-local wall-clock values such as `19:00`, so DST changes keep the intended local send time. A text is skipped when the tenant is inactive, the text is disabled, the scheduler is disabled, no rules are assigned, or GreenAPI settings are incomplete.

Each automatic slot produces a persisted attempt record. Poll sends keep their `scheduled_slot` on the poll row as `rule:<id>:poll:<HH:MM>`, and failed attempts are recorded separately so missed slots are diagnosable.

`GET /api/v1/health` exposes the latest worker heartbeat payload from the database, including `last_tick_at`, `last_success_at`, `polls_sent`, `summaries_sent`, and the last worker error summary when present.

For short-term troubleshooting, set `SCHEDULER_DEBUG_ENABLED=true` on the `scheduler` service. This emits high-volume structured logs for row payloads, runtime config derivation, timezone conversion, rule matching, due-count math, send calls, failures, and heartbeat writes. Turn it back off by removing or setting that one environment flag to `false`.

## Webhooks

GreenAPI callbacks must post poll updates to:

```text
https://your-public-domain.example/webhooks/greenapi/{tenant_id}
```

The webhook handler ignores non-poll updates, unmatched message IDs, and updates for another tenant. Accepted vote changes are recorded in `poll_votes` and `poll_vote_events`.

## Release Checks

Run these before release:

```bash
python -m compileall app tests
ruff check app tests
ruff format --check app tests
pytest
cd web && npm run typecheck
cd web && npm run build
docker compose config --quiet
```

For routing, scheduler, webhook, or persistence changes, also run PostgreSQL-backed tests:

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5433/english_bot pytest
```

## Troubleshooting

- `401` from `/api/v1/docs` or `/api/v1/openapi.json`: mint a new docs session from `/doc`; tokens are short-lived and signed.
- Polls are not sending: confirm the `scheduler` service is running, then inspect `GET /api/v1/health`, tenant GreenAPI settings, text enabled state, scheduler enabled state, assigned rules, and the tenant timezone.
- Webhook events are missing: confirm the GreenAPI webhook URL includes the tenant ID and that `pollMessageWebhook` is enabled.
- Summaries are missing: confirm summaries are enabled and polls have unsummarized sent status.
