# Repository Guidelines

## Project Structure & Module Organization
- `app/`: FastAPI backend. Core files include [`app/main.py`](/home/ari/Desktop/english_bot/app/main.py) for routes, [`app/database.py`](/home/ari/Desktop/english_bot/app/database.py) for PostgreSQL access, [`app/services.py`](/home/ari/Desktop/english_bot/app/services.py) for webhook and poll workflows, and [`app/scheduler.py`](/home/ari/Desktop/english_bot/app/scheduler.py) for APScheduler jobs.
- `web/`: React + TypeScript frontend. Main UI lives in [`web/src/main.tsx`](/home/ari/Desktop/english_bot/web/src/main.tsx) and styles in [`web/src/styles.css`](/home/ari/Desktop/english_bot/web/src/styles.css).
- `tests/`: Pytest suite for API, services, config, scheduler, and UI asset smoke checks.
- Root files: `docker-compose.yml`, backend `Dockerfile`, frontend `web/Dockerfile`, and `README.md`.

## Build, Test, and Development Commands
- `docker compose up --build`: start the full stack locally on `http://127.0.0.1:8988`.
- `python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`: set up backend development.
- `uvicorn app.main:app --reload --port 8000`: run the API locally.
- `cd web && npm install && npm run dev`: run the frontend with Vite.
- `pytest`: run the default Python test suite.
- `TEST_DATABASE_URL=postgresql://... pytest`: run integration tests that require PostgreSQL.
- `cd web && npm run build`: verify the production frontend bundle.

## Coding Style & Naming Conventions
- Python: 4-space indentation, type hints where practical, snake_case for functions, variables, and module-level helpers.
- TypeScript/React: follow the existing single-file UI style in `web/src/main.tsx`; use PascalCase for components and camelCase for helpers/state.
- Keep changes ASCII unless the file already requires Unicode.
- Prefer small, direct functions over framework-heavy abstractions.

## Testing Guidelines
- Add or update pytest coverage for backend behavior changes in `tests/test_*.py`.
- Keep UI smoke assertions in [`tests/test_ui_assets.py`](/home/ari/Desktop/english_bot/tests/test_ui_assets.py) aligned with visible feature changes.
- Before pushing, run:
  - `python -m compileall app tests`
  - `pytest`
  - `cd web && npm run build`

## Commit & Pull Request Guidelines
- Match the existing commit style: short imperative summaries, e.g. `Fix scheduler lifecycle` or `Show poll events per poll with contact details`.
- Keep commits scoped to one change.
- PRs should include: purpose, affected areas (`app/`, `web/`, deploy flow), test results, and screenshots for visible UI changes.

## Security & Configuration Tips
- Do not commit production secrets.
- Local auth defaults to `admin` / `admin`; change that in non-demo environments.
- Webhook and deploy settings should stay in environment configuration, not in source.
