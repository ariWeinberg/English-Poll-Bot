# Architecture

English WhatsApp Poll Bot is a split FastAPI and React application. Keep changes small, typed, and isolated behind the boundaries below.

## Runtime Services

- `api` serves HTTP requests and manual operator actions.
- `scheduler` runs minute-based schedule evaluation in a dedicated container against the shared database.
- `ui` serves the React bundle.
- `db` stores tenants, texts, rules, polls, chat catalogs, roster snapshots, and scheduler planning state.

## Backend Boundaries

- `app/main.py` owns the FastAPI app factory, HTTP routes, request and response models, auth dependencies, and route-level validation.
- `app/core/docs.py` owns short-lived signed tokens for protected Swagger and OpenAPI access.
- `app/core/logging.py` owns JSON/human logging setup, request IDs, request lifecycle logging, and secret redaction.
- `app/services.py` owns workflow orchestration for question generation, poll sending, pool refill, webhook processing, and summaries.
- `app/database.py` owns SQL, row serialization, text schedule-rule persistence, learner analytics aggregation, roster snapshots, random-rule daily plans, and database initialization.
- `app/scheduler.py` owns APScheduler job registration and schedule-rule evaluation.
- `app/scheduler_worker.py` owns the dedicated scheduler process lifecycle used by the deployed `scheduler` service.
- `app/greenapi.py` and `app/question_generator.py` own external service clients and provider-specific payload handling.

Route handlers should stay thin. New business rules belong in service functions. New SQL belongs behind database helper functions rather than directly in routes or frontend code.

## Frontend Boundaries

- `web/src/App.tsx` currently owns the main dashboard shell, route state, API types, and views.
- The authenticated `/learners` route renders the learner progress dashboard and uses tenant-scoped analytics and missed-response endpoints.
- The authenticated text and poll detail routes render roster sync controls, schedule-rule summaries, and poll coverage summaries on top of the existing delivery views.
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

## Logging

The API configures local JSON and human-readable logs through:

- `LOG_LEVEL`
- `LOG_FORMAT`
- `LOG_FILE`
- `LOG_HUMAN_FILE`
- `LOG_REQUEST_BODY_ENABLED`

Logs include request lifecycle events, request IDs, scheduler decisions, webhook decisions, poll sending, pool refill, summaries, provider-call failures, and exception traces. Secret-like keys are redacted before log records are written.

See `docs/runbook.md` for the operator-facing checklist.

## Documentation Rule

Any change that alters setup, deployment, public API behavior, scheduler behavior, GreenAPI/Gemini integration, or user-visible workflows must update `README.md`, this architecture note, or the relevant tests in the same pull request.
