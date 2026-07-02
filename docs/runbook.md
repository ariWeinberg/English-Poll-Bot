# Operations Runbook

## Access

- App users authenticate through `/api/v1/auth/login`.
- Public Swagger and OpenAPI are disabled at `/docs` and `/openapi.json`.
- Logged-in users can open the in-app `/doc` page and mint a short-lived Swagger session through `POST /api/v1/docs/session`.
- The protected docs endpoints are `/api/v1/docs?token=...` and `/api/v1/openapi.json?token=...`.

## Local Logging

The API writes local logs with secret redaction by default:

- `LOG_LEVEL`: standard Python log level, default `INFO`.
- `LOG_FORMAT`: `human` or `json` for stdout and stream formatting, default `human`.
- `LOG_FILE`: JSON-lines file, default `logs/app.jsonl`.
- `LOG_HUMAN_FILE`: readable log file, default `logs/app.log`.
- `LOG_REQUEST_BODY_ENABLED`: log redacted JSON request bodies when set to `true`, default `false`.
- `SCHEDULER_DEBUG_ENABLED`: worker-only ultra-verbose scheduler tracing when set to `true`, default `false`.

Logged events include request start/finish with request IDs, scheduler ticks, skipped scheduler work, per-slot send attempts, pool refills, summary sends, webhook decisions, and exceptions. The same logging stack also writes to stdout, so Compose and container log collectors can see API and scheduler worker events without enabling debug mode.

## Scheduler

The dedicated `scheduler` worker runs every minute in UTC and evaluates recurring rules in each tenant's local timezone. Rule times stay stored as tenant-local wall-clock values such as `19:00`, so DST changes keep the intended local send time. A text is skipped when the tenant is inactive, the text is disabled, the scheduler is disabled, no rules are assigned, or GreenAPI settings are incomplete.

In local development, `uvicorn app.main:app --reload --port 8000` is not enough by itself. Start `python -m app.scheduler_worker` in a second terminal against the same `DATABASE_URL`, otherwise recurring sends will never fire even though manual send still works.

Each automatic slot produces a persisted attempt record. Poll sends keep their `scheduled_slot` on the poll row as `rule:<id>:poll:<HH:MM>`, and failed attempts are recorded separately so missed slots are diagnosable.

`GET /api/v1/health` exposes the latest worker heartbeat payload from the database, including `last_tick_at`, `last_success_at`, `polls_sent`, `summaries_sent`, and the last worker error summary when present.
`GET /api/v1/readiness` performs a stronger platform check. It validates the database connection and requires a recent successful scheduler heartbeat before reporting the platform ready for release verification.

For short-term troubleshooting, set `SCHEDULER_DEBUG_ENABLED=true` on the `scheduler` service. This emits high-volume structured logs for row payloads, runtime config derivation, timezone conversion, rule matching, due-count math, send calls, failures, and heartbeat writes. Turn it back off by removing or setting that one environment flag to `false`.

Startup initialization seeds only the default admin tenant on a blank database. It does not create a sample text or sample rules, and normal restarts or updates will not recreate deleted sample scheduling data.

## Webhooks

Connector callbacks must post poll updates to the provider-specific public endpoint:

```text
https://your-public-domain.example/webhooks/greenapi/{tenant_id}
https://your-public-domain.example/webhooks/waha/{tenant_id}
```

Every request to those endpoints is stored durably in the authenticated Webhook Inbox at `/webhooks`. Stored rows keep the exact raw JSON payload, provider-neutral message identity when available, optional provider metadata, and a final decision state:

- `accepted` with reason `handled`
- `ignored` with reasons such as `not_poll_update`, `poll_not_found`, and `poll_not_found_after_enrichment`
- `error` with a short error summary when processing raises or the payload is invalid

Accepted vote changes are still recorded in `poll_votes` and `poll_vote_events`; the inbox is an operator-facing audit trail, not a replacement for those tables or for structured logs.

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
- Release smoke passes on `/api/v1/health` but fails on `/api/v1/readiness`: wait for a successful scheduler heartbeat, then inspect the scheduler worker logs and the heartbeat payload in `GET /api/v1/health`.
- Webhook events are missing: confirm the GreenAPI webhook URL includes the tenant ID and that `pollMessageWebhook` is enabled, then inspect the `/webhooks` page for ignored or error rows.
- Summaries are missing: confirm summaries are enabled and polls have unsummarized sent status.
- Deploy fails while bringing up `ui`: the UI container now has its own `/` healthcheck and no longer blocks on API health during `docker compose up`; rely on the post-deploy smoke test to wait for both `/` and `/api/v1/health`.

## Roadmap Reference

The year-long implementation plan, delivery ordering, and acceptance criteria live in [`docs/roadmap.md`](./roadmap.md). Use it as the source of truth when deciding which operational, provider, analytics, curriculum, or pilot-readiness work to tackle next.
