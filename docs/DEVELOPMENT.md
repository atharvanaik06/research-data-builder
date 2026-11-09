# Development Guide

## Prerequisites

- Python 3.12 or newer
- Git
- Docker with Compose support for the containerized workflow

The application can run directly in Python without Docker. PostgreSQL is included in Compose now so Phase 2 can add persistence without changing the local operating model.

## Python setup

Create an isolated environment and install the locked development dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.lock
cp .env.example .env
```

Run the application directly from the source tree:

```bash
.venv/bin/uvicorn research_data_builder.main:app --app-dir src --reload
```

Using `--app-dir src` ensures development runs always use the current source files. The CI workflow also performs a regular package installation to verify that the distributable project is valid.

## Docker setup

Start the API, worker, and PostgreSQL:

```bash
docker compose up --build
```

Check service state:

```bash
docker compose ps
```

Stop the services without deleting PostgreSQL data:

```bash
docker compose down
```

The Compose stack exposes:

| Service | Address |
|---|---|
| Browser application | <http://localhost:8000/app> |
| API | <http://localhost:8000> |
| API documentation | <http://localhost:8000/docs> |
| PostgreSQL | `localhost:5432` |
| Worker | Background process in the Compose stack |

The liveness route at `/health` does not query PostgreSQL. The readiness route at `/ready` returns `200` only when the database can execute a query.

## Database migrations

Start PostgreSQL and apply every migration from inside the application image:

```bash
docker compose up -d postgres
docker compose run --rm api alembic upgrade head
```

Inspect the active revision:

```bash
docker compose run --rm api alembic current
```

Generate offline SQL for review without connecting to PostgreSQL:

```bash
.venv/bin/alembic upgrade head --sql
```

Schema changes must be represented by a reviewed Alembic revision. Do not modify a shared database manually.

## Configuration

Settings use the `RESEARCH_DATA_` environment prefix.

| Variable | Default | Purpose |
|---|---|---|
| `RESEARCH_DATA_ENVIRONMENT` | `development` | `development`, `test`, or `production` |
| `RESEARCH_DATA_LOG_LEVEL` | `INFO` | Python log level |
| `RESEARCH_DATA_DATABASE_URL` | local PostgreSQL URL | Database connection string |
| `RESEARCH_DATA_TEST_DATABASE_URL` | unset | Enables real PostgreSQL integration tests |
| `RESEARCH_DATA_FRED_API_KEY` | unset | Required for live FRED requests |
| `RESEARCH_DATA_PROVIDER_HTTP_TIMEOUT_SECONDS` | `15` | Timeout for one provider request attempt |
| `RESEARCH_DATA_PROVIDER_HTTP_MAX_ATTEMPTS` | `3` | Maximum attempts for transient provider failures |
| `RESEARCH_DATA_PROVIDER_CACHE_TTL_HOURS` | `24` | Valid lifetime for a cached provider response |
| `RESEARCH_DATA_ARTIFACT_ROOT` | `artifacts` | Controlled root for generated build bundles |
| `RESEARCH_DATA_SESSION_COOKIE_NAME` | `research_data_session` | Opaque browser-session cookie name |
| `RESEARCH_DATA_SESSION_TTL_HOURS` | `168` | Session lifetime in hours |
| `RESEARCH_DATA_WORKER_POLL_SECONDS` | `1` | Delay between empty queue checks |
| `RESEARCH_DATA_WORKER_LEASE_SECONDS` | `60` | Worker lease duration in seconds |
| `RESEARCH_DATA_MAX_OUTSTANDING_BUILDS_PER_USER` | `5` | Maximum queued and running builds for one user |
| `RESEARCH_DATA_MAX_RECIPE_BYTES` | `65536` | Maximum stored recipe size in bytes |

Copy `.env.example` to `.env` for local overrides. `.env` is ignored by Git. Never commit provider keys, passwords, or private research credentials.

## Quality checks

Format source files:

```bash
.venv/bin/ruff format .
```

Run the same quality gates used by CI:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src tests
.venv/bin/pytest --cov=research_data_builder --cov-report=term-missing
```

The coverage gate is configured at 90%. New functionality should include tests for success, validation, and failure behavior.

Integration tests are skipped when `RESEARCH_DATA_TEST_DATABASE_URL` is unset. CI supplies a PostgreSQL service, applies the migration, checks for model/schema drift, runs the tests, and verifies downgrade/upgrade behavior.

## Sample bundle

Generate the checked-in Phase 6 example from deterministic provider fixtures:

```bash
PYTHONPATH=src .venv/bin/python scripts/generate_sample_bundle.py
```

The command writes only below `examples/sample_bundle/builds/<build-id>`. It requires no provider key or network connection. Review `checksums.sha256` to verify the exported files.

## Dependency workflow

- `pyproject.toml` declares supported dependency ranges and tool configuration.
- `requirements.lock` records the complete development and CI environment.
- `requirements.runtime.lock` records only production runtime dependencies.
- The Docker image installs the runtime lock and then installs Research Data Builder with `--no-deps`.

When dependencies intentionally change, regenerate and review both lock files, reinstall into a clean environment, and run the full quality suite.

## Current verification

The current foundation is considered healthy when:

1. `/health` returns service metadata.
2. `/docs` and `/openapi.json` are available.
3. invalid configuration fails validation.
4. logs are emitted as structured JSON.
5. formatting, linting, strict typing, and tests pass.
6. the production package installs from the runtime lock.
7. Alembic can upgrade an empty PostgreSQL database and reports no schema drift.
8. PostgreSQL integration tests verify precision, uniqueness, ordering, and rollback.
9. CI validates both Python quality checks and the container build.
10. FRED and World Bank fixture contract tests pass without external network access.
11. The browser application loads at `/app`.
12. Cache, audit, ownership, limit, and job tests pass.
