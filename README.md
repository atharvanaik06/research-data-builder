# Research Data Builder

[![CI](https://github.com/atharvanaik06/research-data-builder/actions/workflows/ci.yml/badge.svg)](https://github.com/atharvanaik06/research-data-builder/actions/workflows/ci.yml)

Research Data Builder turns public economic APIs into validated, documented, and reproducible research datasets.

## The problem

A researcher studying growth, inflation, and unemployment across countries may spend more time collecting and cleaning data than analyzing it:

```text
Find indicators across providers
→ download separate files
→ normalize country and date identifiers
→ reconcile units and frequencies
→ join tables
→ investigate missing observations
→ document every source and transformation
→ repeat the work when data changes
```

Research Data Builder converts that work into a saved dataset recipe.

## The intended workflow

1. Select supported providers, indicators, countries, and dates.
2. Review units, frequencies, and proposed transformations.
3. Save a versioned recipe.
4. Run a deterministic dataset build.
5. Inspect missing values, coverage, and validation warnings.
6. Export a research bundle containing data, a codebook, provenance, citations, and a checksum.
7. Rebuild or refresh the dataset later from the same recipe.

## First useful product

The local MVP will support:

- FRED and World Bank provider connectors;
- a common normalized observation schema;
- versioned YAML/JSON dataset recipes;
- country, date, frequency, and variable harmonization;
- explicit transformations and missing-value policies;
- deterministic builds using Polars or DuckDB;
- coverage and data-quality validation;
- CSV and Parquet exports;
- generated codebook, manifest, citations, and SHA-256 checksum;
- exact input and transformation lineage;
- fixture-driven tests that do not depend on live provider availability.

Additional providers, vintage-aware backtesting, and AI-assisted recipe creation are later phases.

Phase 7 is complete. The product includes secure accounts, private research ownership, immutable builds, a PostgreSQL background queue, cached provider inputs, activity history, user limits, and a browser interface.

## Current product

Phases 1 through 7 are complete. A researcher can now use the full local workflow from a browser:

- FastAPI application, validated settings, and structured logging;
- Docker and PostgreSQL local stack;
- GitHub Actions quality and container checks;
- async SQLAlchemy repositories and Alembic migrations;
- provider-series metadata, synchronization audit records, append-only source observations, and source-change events;
- a provider-neutral connector contract and capability registry;
- FRED indicator search, metadata, and paginated observation normalization;
- World Bank indicator search, entity catalog, and paginated multi-country observations;
- shared HTTP timeouts, bounded retries, rate-limit handling, and typed failures;
- idempotent provider catalog refresh with stable metadata fingerprints;
- fixture-driven connector tests that never require live provider availability;
- strict dataset recipes with safe JSON/YAML import and export;
- editable drafts and immutable, content-addressed recipe versions;
- normalized recipe variables and ordered transformation declarations;
- provider metadata resolution and deterministic build-plan identities;
- idempotent planned builds with exact provider requests and metadata fingerprints;
- versioned recipe and build-planning API routes;
- Polars-based long-form staging and deterministic wide-table execution;
- versioned entity aliases and canonical period representations;
- explicit aggregation, lag, difference, percent-change, and scaling operations;
- rejection of ambiguous or unsupported frequency conversions;
- outer, inner, and left joins with unmatched-key reporting;
- durable execution summaries and bounded dataset previews;
- blocking validation for duplicate keys, types, ranges, and recipe rules;
- coverage, missing-value, and unmatched-join findings with explicit severity;
- source-to-output column lineage and a canonical logical-dataset checksum;
- deterministic CSV and Parquet export with codebook, citations, manifest, and reports;
- checksum-verified artifact downloads and build-to-build comparisons;
- transactional validation, lineage, export metadata, and final build success;
- secure account sessions and private ownership checks;
- durable background jobs with progress, retries, and cancellation;
- a 24-hour provider-input cache with an explicit refresh option;
- per-user recipe and outstanding-build limits;
- a private activity history for recipe, build, worker, and download events;
- a guided browser workflow for recipes, builds, previews, validation, and downloads;
- PostgreSQL integration tests for decimal precision, constraints, ordering, and rollback.
- local and S3-compatible artifact storage with checksum and size checks;
- an embedded worker mode for hosts without a separate free worker service;
- a zero-cost Render deployment description;
- a validated AWS Terraform production reference design.

See the checked-in [sample research bundle](examples/sample_bundle/README.md) without running the application.

## Quick start

Requirements: Python 3.12 or newer. Docker is optional for the containerized workflow.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
cp .env.example .env
.venv/bin/uvicorn research_data_builder.main:app --app-dir src --reload
```

Then open:

- Browser application: <http://localhost:8000/app>
- API health: <http://localhost:8000/health>
- Dependency readiness: <http://localhost:8000/ready>
- Interactive API documentation: <http://localhost:8000/docs>
- OpenAPI document: <http://localhost:8000/openapi.json>

Run all local quality checks:

```bash
.venv/bin/ruff format --check .
.venv/bin/ruff check .
.venv/bin/mypy src tests
.venv/bin/pytest --cov=research_data_builder --cov-report=term-missing
```

Generate the deterministic demonstration bundle:

```bash
PYTHONPATH=src .venv/bin/python scripts/generate_sample_bundle.py
```

Or start the API and PostgreSQL with Docker:

```bash
docker compose up --build
```

## Project documents

- [Product requirements](docs/REQUIREMENTS.md)
- [System design](docs/SYSTEM_DESIGN.md)
- [Hand-drawn system design diagram](docs/research-data-builder-system-design.png)
- [Interactive system design](docs/research-data-builder-design.html)
- [Phased build and commit plan](docs/ROADMAP.md)
- [Database design and migrations](docs/DATABASE.md)
- [Provider connectors](docs/PROVIDERS.md)
- [Recipe and build planning](docs/RECIPES.md)
- [Transformation engine](docs/ENGINE.md)
- [Validation and research bundles](docs/BUNDLES.md)
- [Authentication and browser sessions](docs/AUTHENTICATION.md)
- [Background build jobs](docs/BACKGROUND_JOBS.md)
- [Provider-input cache](docs/PROVIDER_CACHE.md)
- [Browser workflow](docs/WEB_APP.md)
- [Audit history and user limits](docs/AUDIT_AND_LIMITS.md)
- [AWS infrastructure](docs/AWS_INFRASTRUCTURE.md)
- [Zero-cost demo deployment](docs/ZERO_COST_DEPLOYMENT.md)
- [AWS recruiter and interview guide](docs/AWS_RECRUITER_GUIDE.md)
- [Adversarial review findings and engineering backlog](docs/REVIEW_FINDINGS.md)
- [Development guide](docs/DEVELOPMENT.md)

## Current status

Phases 1 through 7 are complete. Phase 8 now includes an AWS production reference design and a zero-cost demo deployment design.

The next step is to connect the free service accounts and deploy the public demo. The project does not create paid AWS resources.
