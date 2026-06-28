# English WhatsApp Poll Bot

A split FastAPI + React app for multi-tenant WhatsApp learning polls. Each tenant can manage its own GreenAPI and Gemini settings, and each tenant can create multiple texts with their own WhatsApp chat, schedule rules, and attachment.

## Run With Docker

```bash
docker compose up --build
```

Open `http://127.0.0.1:8988`.

Default tenant login on first run:

- username: `admin`
- password: `admin`

Change these in the dashboard after logging in. Passwords are stored as salted password hashes.

The Compose stack starts:

- `ui`: React app served by nginx on port `8988`
- `api`: FastAPI REST API on the internal Compose network
- `db`: PostgreSQL 16
- `postgres_data`: persistent database volume
- `uploads_data`: persistent uploaded text attachments

## Local Development

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
export DATABASE_URL=postgresql://postgres:postgres@localhost:5433/english_bot
uvicorn app.main:app --reload --port 8000
cd web
npm install
npm run dev
```

For local development, run your own PostgreSQL database or use the Compose database service. Vite proxies `/api` and `/webhooks` to `http://localhost:8000`.

## REST API

Authenticated API routes live under `/api/v1` and use `Authorization: Bearer <token>`.

- `POST /api/v1/auth/login`
- CRUD: `/api/v1/tenants`, `/api/v1/texts`, `/api/v1/polls`, `/api/v1/poll-votes`
- Text schedule rules: `GET|POST /api/v1/texts/{text_id}/schedule-rules`, `PATCH|DELETE /api/v1/texts/{text_id}/schedule-rules/{rule_id}`
- Learner analytics: `GET /api/v1/learners`, `GET /api/v1/learners/{voter_wid}`
- Roster and coverage: `GET|POST|PATCH /api/v1/texts/{text_id}/roster...`, `GET /api/v1/polls/{poll_id}/coverage`
- Actions: `/api/v1/questions/preview`, `/api/v1/polls/send-now`, `/api/v1/summaries/send-now`
- CSV export: `/api/v1/polls/export.csv`
- Protected docs: `POST /api/v1/docs/session`, then open `/api/v1/docs?token=...` or `/api/v1/openapi.json?token=...`

List endpoints support `page` and `page_size`. Resource-specific filters include tenant/text IDs, active/enabled/status fields, search fields, and poll sent date bounds.

Public FastAPI Swagger and OpenAPI endpoints are disabled. Logged-in UI users can open `/doc` to launch a short-lived Swagger session.

## Logging

Local logging is enabled by default with JSON and human-readable files:

- `LOG_LEVEL`, default `INFO`
- `LOG_FORMAT`, default `human`
- `LOG_FILE`, default `logs/app.jsonl`
- `LOG_HUMAN_FILE`, default `logs/app.log`
- `LOG_REQUEST_BODY_ENABLED`, default `false`

Logs include request IDs, request lifecycle events, scheduler decisions, webhook decisions, poll sends, pool refills, summaries, and exceptions with secret redaction.

## What You Can Configure

- Tenants with their own GreenAPI and Gemini settings
- Multiple texts per tenant
- Per-text WhatsApp group chat ID
- Per-text schedule rules for poll and summary delivery
- Daily, weekday, month-date, and random-window scheduling with fixed or ranged send counts
- Optional file attachment for each text
- Learner progress dashboard with tenant-scoped leaderboard, missed-response tracking, and per-contact answer history
- Text-level WhatsApp group roster sync with coverage exclusions
- Poll-level participation coverage with non-responder lists
- Separate landing, login, dashboard, learner analytics, and texts pages

## Webhooks

GreenAPI must send incoming poll updates to:

```text
https://your-public-domain.example/webhooks/greenapi/{tenant_id}
```

Enable these GreenAPI settings:

- `incomingWebhook`
- `pollMessageWebhook`

Operational guidance for scheduler behavior, webhook diagnostics, logging, and release checks lives in `docs/runbook.md` and is summarized in the authenticated `/doc` app page.

## Test

```bash
python -m compileall app tests
ruff check app tests
ruff format --check app tests
pytest
cd web
npm install
npm run typecheck
npm run build
cd ..
docker compose config --quiet
```

Database integration tests require PostgreSQL:

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5433/english_bot pytest
```

## CI/CD

Pushes and pull requests run:

- Python compile checks
- Ruff lint and format checks
- backend tests
- frontend type checks and builds
- compose config validation

Keep documentation current with behavior changes. Changes that alter setup, deployment, API behavior, scheduling, provider integrations, or user-visible workflows should update `README.md`, `docs/architecture.md`, or tests in the same pull request.

Pushes to the `release` branch deploy to the production server by SSH. The deploy job reads `secrets.SSH_PRIVATE_KEY` from the GitHub `release` environment, writes it to a temporary key file on the runner, and SSHes into the server to run `docker-compose down --remove-orphans` followed by `docker-compose up -d --build --remove-orphans` in the checked-out repo.

Required GitHub `release` environment secrets for deploy:

- `DEPLOY_HOST`
- `DEPLOY_USER`
- `DEPLOY_PATH`
- optional `DEPLOY_PORT`
- optional `DEPLOY_BASE_URL` for the post-deploy smoke test

The server keeps production credentials in its local Compose environment file. The repository does not store production secrets.
