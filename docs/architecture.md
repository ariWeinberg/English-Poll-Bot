# Architecture

English WhatsApp Poll Bot is a split FastAPI and React application. Keep changes small, typed, and isolated behind the boundaries below.

## Backend Boundaries

- `app/main.py` owns HTTP routes, request and response models, auth dependencies, and route-level validation.
- `app/services.py` owns workflow orchestration for question generation, poll sending, pool refill, webhook processing, and summaries.
- `app/database.py` owns SQL, row serialization, persistence helpers, and database initialization.
- `app/scheduler.py` owns APScheduler job registration and lifecycle integration.
- `app/greenapi.py` and `app/question_generator.py` own external service clients and provider-specific payload handling.

Route handlers should stay thin. New business rules belong in service functions. New SQL belongs behind database helper functions rather than directly in routes or frontend code.

## Frontend Boundaries

- `web/src/App.tsx` currently owns the main dashboard shell, route state, API types, and views.
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

## Documentation Rule

Any change that alters setup, deployment, public API behavior, scheduler behavior, GreenAPI/Gemini integration, or user-visible workflows must update `README.md`, this architecture note, or the relevant tests in the same pull request.
