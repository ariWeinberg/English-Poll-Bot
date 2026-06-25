# English WhatsApp Poll Bot

A Python FastAPI app for multi-tenant WhatsApp learning polls. Each tenant can manage its own GreenAPI and Gemini settings, and each tenant can create multiple texts with their own WhatsApp chat, schedule, and attachment.

## Run With Docker

```bash
docker compose up --build
```

Open `http://127.0.0.1:8988`.

Default tenant login on first run:

- username: `admin`
- password: `admin`

Change these in the dashboard after logging in. Passwords are stored as plaintext for the V1 MVP.

The Compose stack starts:

- `web`: FastAPI app on port `8988`
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
uvicorn app.main:app --reload
```

For local development, run your own PostgreSQL database or use the Compose database service.

## What You Can Configure

- Tenants with their own GreenAPI and Gemini settings
- Multiple texts per tenant
- Per-text WhatsApp group chat ID
- Per-text morning/evening poll times
- Per-text morning/evening summary times
- Optional file attachment for each text
- Separate landing, login, dashboard, and texts pages

## Webhooks

GreenAPI must send incoming poll updates to:

```text
https://your-public-domain.example/webhooks/greenapi
```

Enable these GreenAPI settings:

- `incomingWebhook`
- `pollMessageWebhook`

## Test

```bash
pytest
```

Database integration tests require PostgreSQL:

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5433/english_bot pytest
```
