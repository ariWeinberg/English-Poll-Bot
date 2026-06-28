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

Logged events include request start/finish with request IDs, scheduler ticks, skipped scheduler work, poll send attempts, pool refills, summary sends, webhook decisions, and exceptions.

## Scheduler

The scheduler runs every minute in UTC and evaluates each enabled text in the tenant timezone. It sends polls at the configured morning/evening times and summaries at the configured summary times. A tenant is skipped when scheduler delivery is disabled or GreenAPI settings are incomplete.

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
- Polls are not sending: confirm tenant GreenAPI settings, text enabled state, scheduler enabled state, and local timezone.
- Webhook events are missing: confirm the GreenAPI webhook URL includes the tenant ID and that `pollMessageWebhook` is enabled.
- Summaries are missing: confirm summaries are enabled and polls have unsummarized sent status.
