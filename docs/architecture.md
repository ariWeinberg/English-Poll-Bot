# Architecture

English WhatsApp Poll Bot is a split FastAPI and React application. Keep changes small, typed, and isolated behind the boundaries below.

## Runtime Services

- `api` serves HTTP requests and manual operator actions.
- `scheduler` runs minute-based schedule evaluation in a dedicated container against the shared database.
- `ui` serves the React bundle.
- `db` stores tenants, texts, rules, polls, chat catalogs, roster snapshots, and scheduler planning state.

## Backend Boundaries

- `app/main.py` owns the FastAPI app factory, HTTP routes, request and response models, auth dependencies, and route-level validation. It does not own scheduler lifecycle.
- `app/core/docs.py` owns short-lived signed tokens for protected Swagger and OpenAPI access.
- `app/core/logging.py` owns JSON/human logging setup, request IDs, request lifecycle logging, and secret redaction.
- `app/services.py` owns workflow orchestration for question generation, poll sending, pool refill, connector-aware webhook processing, and summaries.
- `app/database.py` owns SQLAlchemy-backed runtime access, row serialization, text schedule-rule persistence, learner analytics aggregation, roster snapshots, random-rule daily plans, scheduler heartbeat state, scheduled send-attempt persistence, incoming webhook inbox persistence, connector records, poll review metadata, and database initialization.
- `app/scheduler.py` owns APScheduler job registration, tenant-local schedule-rule evaluation, worker heartbeat writes, and scheduled send-attempt bookkeeping.
- `app/scheduler_worker.py` owns the dedicated scheduler process lifecycle used by the deployed `scheduler` service.
- `app/greenapi.py`, `app/waha.py`, `app/whatsapp.py`, and `app/question_generator.py` own external service clients, provider adapters, and normalized WhatsApp event handling.

Route handlers should stay thin. New business rules belong in service functions. New SQL belongs behind database helper functions rather than directly in routes or frontend code.

## Frontend Boundaries

- `web/src/App.tsx` currently owns the main dashboard shell, route state, API types, and views.
- The authenticated `/dashboard` route renders the executive BI overview, including time-scoped poll stats, delivery-health summaries, and drill-through links into learners and poll/text detail views.
- The dashboard also exposes a teacher workflow checklist and next-step shortcut so onboarding and day-to-day setup live alongside the BI view instead of being buried in settings.
- The authenticated `/learners` route renders the learner intervention dashboard and uses tenant-scoped learner summary, ranked risk slices, segment filters, and missed-response endpoints.
- The learner dashboard also renders derived focus-area and data-confidence markers so operators can distinguish sparse data from actionable risk.
- The authenticated `/settings` route renders workspace configuration plus connector diagnostics, including recent webhook activity and provider status.
- The authenticated `/settings` route also renders a pilot-readiness checklist so launch blockers are visible alongside connector state.
- The authenticated text and poll detail routes render roster sync controls, schedule-rule summaries, and poll coverage summaries on top of the existing delivery views.
- The authenticated poll detail and edit flows render review state and review notes so teachers can approve, disable, archive, or request edits on generated questions.
- The authenticated `/polls` route also exposes review-state filters and a quality summary so weak or review-required questions are visible before teachers drill into a detail page.
- The authenticated `/webhooks` route renders the persisted webhook inbox with tenant-scoped filters, provider-neutral message IDs, and inline raw-payload inspection.
- The webhook inbox also exposes retry actions for errored or ignored rows, with retry counters stored on the webhook record itself.
- The authenticated `/doc` route renders operational guidance and opens Swagger through `POST /api/v1/docs/session`.
- `web/src/main.tsx` only mounts React.
- `web/src/styles.css` owns global styling and page-specific class rules.

When adding frontend behavior, keep API calls typed, keep formatting helpers pure, and extract reusable or stateful UI into focused components instead of expanding one large branch of `App.tsx`.

## Quality Gates

Local and CI verification use the same commands:

```bash
python -m compileall app tests
ruff check app tests
ruff format --check app tests
pytest
cd web && npm install && npm run typecheck && npm run build
docker compose config --quiet
```

Database-backed tests require PostgreSQL and should be run before release changes that touch persistence or scheduling:

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5433/english_bot pytest
```

## Protected API Docs

Public FastAPI docs are disabled at `/docs` and `/openapi.json`. Authenticated users call `POST /api/v1/docs/session` with the existing bearer token to receive a short-lived docs token. Swagger UI is served from `/api/v1/docs?token=...`, and OpenAPI JSON is served from `/api/v1/openapi.json?token=...`.

## Health And Readiness

`GET /api/v1/health` is the liveness-style probe. It exposes the latest scheduler heartbeat payload from the database without forcing a hard readiness decision.

`GET /api/v1/readiness` is the stronger release-check endpoint. It requires a reachable database and a recent successful scheduler heartbeat before it reports ready, so deploy smoke tests can distinguish "the API process is alive" from "the full platform is operational."

## Logging

The API configures local JSON and human-readable logs through:

- `LOG_LEVEL`
- `LOG_FORMAT`
- `LOG_FILE`
- `LOG_HUMAN_FILE`
- `LOG_REQUEST_BODY_ENABLED`
- `SCHEDULER_DEBUG_ENABLED`

Logs include request lifecycle events, request IDs, scheduler decisions, worker heartbeat updates, scheduled-slot attempt records, webhook decisions, poll sending, pool refill, summaries, provider-call failures, and exception traces. Secret-like keys are redacted before log records are written. The logging stack writes to configured files and to stdout so container logs expose normal worker lifecycle and tick activity without forcing debug mode. When `SCHEDULER_DEBUG_ENABLED=true`, only the dedicated scheduler worker adds dense structured trace events for row loading, runtime normalization, rule evaluation, due-count math, send attempts, and heartbeat writes.

See `docs/runbook.md` for the operator-facing checklist.

## Documentation Rule

Any change that alters setup, deployment, public API behavior, scheduler behavior, GreenAPI/Gemini integration, or user-visible workflows must update `README.md`, this architecture note, or the relevant tests in the same pull request.

For the one-year R&D program and its delivery order, use [`docs/roadmap.md`](./roadmap.md) as the canonical planning document. Keep that file current when roadmap scope, sequencing, acceptance criteria, or quarter ordering changes.
