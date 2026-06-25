# English WhatsApp Poll Bot

A Python FastAPI app for multi-tenant WhatsApp learning polls. Each tenant can manage its own GreenAPI and Gemini settings, and each tenant can create multiple texts with their own WhatsApp chat, schedule, and attachment.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Run the app and configure everything from the UI.

## Run

```bash
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## What You Can Configure

- Tenants with their own GreenAPI and Gemini settings
- Multiple texts per tenant
- Per-text WhatsApp group chat ID
- Per-text morning/evening poll times
- Per-text morning/evening summary times
- Optional file attachment for each text

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
