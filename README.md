# Research Data Builder

[![CI](https://github.com/atharvanaik06/research-data-builder/actions/workflows/ci.yml/badge.svg)](https://github.com/atharvanaik06/research-data-builder/actions/workflows/ci.yml)

Research Data Builder combines FRED and World Bank data into validated research datasets. It saves the inputs used for each build so researchers can reproduce a result after a provider revises its data.

[Open the app](https://research-data-builder.onrender.com/app) · [View a sample bundle](examples/sample_bundle/README.md) · [Read the system design](docs/SYSTEM_DESIGN.md)

## See what happens after a source revision

This fixture joins 2023 US GDP growth with FRED unemployment. The refreshed build sees a simulated World Bank revision. Replay uses the original observations with both provider connectors disabled.

| Build | US GDP growth | Logical dataset SHA-256 |
| --- | ---: | --- |
| Original | 2.5% | `2716f65e0634773fc573ee92092197b096e558514e3aaf25d8142ba97a9e1146` |
| Fresh data | 2.7% | `575644d01fd64874874928c8d0b5c83bcdbee6509061edea455359a59e03a0e0` |
| Offline replay | 2.5% | `2716f65e0634773fc573ee92092197b096e558514e3aaf25d8142ba97a9e1146` |

Run the example with Python 3.12 or newer. The fixture requires no account, API keys, or database.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
PYTHONPATH=src .venv/bin/python scripts/demo_replay.py
```

## How a build works

1. Save a recipe with indicators, dates, join rules, and transformations. The planner freezes the recipe and resolves provider metadata.
2. A PostgreSQL-backed worker retrieves and snapshots normalized observations. Polars harmonizes dates and frequencies, applies the recipe, and builds the dataset.
3. Validation checks keys, ranges, coverage, and missing values. The export contains CSV or Parquet, a codebook, provenance, citations, and checksums.
4. **Build with fresh data** bypasses the provider cache. **Replay saved inputs** uses the original snapshot IDs even after the cache expires. Replay runs the installed transformer and reports version drift separately from checksum equality.

The hosted app runs FastAPI and an embedded worker on Render. Neon PostgreSQL holds build state and input snapshots, and S3-compatible object storage holds downloadable bundles. The [deployment guide](docs/ZERO_COST_DEPLOYMENT.md) covers setup and restart verification.

## Run the app locally

```bash
cp .env.example .env
docker compose up --build
```

Open the [browser app](http://localhost:8000/app) or [API docs](http://localhost:8000/docs). Configure a FRED API key in `.env` for live FRED requests. See the [development guide](docs/DEVELOPMENT.md) for local tests and PostgreSQL integration checks.
