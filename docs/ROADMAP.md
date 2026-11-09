# Research Data Builder Phased Build and Commit Plan

## How we will work

Every phase ends with working behavior, tests, updated documentation, and a concrete demonstration. We commit each coherent engineering outcome and push regularly. Milestone phases are moments for README polish, demonstrations, and releases—not the only times code reaches GitHub.

## Phase 0: Define the useful product

**Status:** complete.

**Goal:** narrow the idea to reproducible research-dataset construction from supported public APIs.

Decisions:

- The product is not a universal downloader.
- The first providers are FRED and World Bank.
- Value comes from harmonization, validation, provenance, and reproducibility.
- PostgreSQL stores workflow state and lineage; Parquet/files hold analytical artifacts.
- AI assistance is optional and cannot replace deterministic recipes.

Commit:

1. `docs: pivot product to reproducible research datasets`

Exit condition: a researcher can understand what time the tool saves and what appears in the final export bundle.

## Phase 1: Professional service foundation

**Status:** complete.

Delivered:

- FastAPI application with liveness and OpenAPI.
- Typed environment configuration.
- Structured JSON logging.
- Locked development and runtime dependencies.
- Ruff, Mypy, pytest, and coverage enforcement.
- Dockerfile and Compose PostgreSQL stack.
- GitHub Actions Python and container validation.

Representative commits:

```text
chore: initialize FastAPI project and developer tooling
feat: add health endpoint and environment settings
build: add containerized local development stack
ci: validate formatting types and tests
```

## Phase 2: Provider-data and provenance foundation

**Status:** complete.

Delivered:

- Async SQLAlchemy database lifecycle and readiness.
- Alembic migration system.
- Provider-series metadata.
- Retrieval/synchronization audit records.
- Append-only decimal-safe observation versions.
- Source-change events and deterministic uniqueness keys.
- Transaction-controlled repositories.
- PostgreSQL constraint, ordering, precision, and rollback tests.
- Migration drift and round-trip checks in CI.

The current schema is not the final product schema. It is the provider-input history under future dataset builds.

## Phase 3: Build the provider connector framework

**Status:** complete.

**Goal:** retrieve FRED and World Bank data through one tested contract.

Delivered:

- Provider protocol and capability metadata.
- Normalized indicator and observation domain objects.
- Shared HTTP timeout, retry, pagination, and error handling.
- FRED metadata/search and observation connector.
- World Bank indicator/entity and observation connector.
- Decimal, date, missing-value, unit, and frequency normalization.
- Deterministic fixtures and connector contract tests.
- Provider catalog refresh service.

Implementation notes:

- FRED requires `RESEARCH_DATA_FRED_API_KEY`; World Bank is keyless.
- Provider calls use configurable timeouts and at most three attempts by default.
- Retries cover transport failures, HTTP 429, and retryable server failures.
- FRED's `.` marker and World Bank's `null` become explicit missing observations.
- Decimal values never pass through binary floating-point conversion.
- Provider metadata refreshes use stable SHA-256 fingerprints.
- Live provider APIs are deliberately excluded from CI; deterministic HTTP fixtures exercise the same connector code.

Likely commits:

1. `feat: define provider connector contract`
2. `feat: add shared provider HTTP policies`
3. `feat: implement FRED indicator connector`
4. `feat: implement World Bank indicator connector`
5. `feat: normalize provider observations and metadata`
6. `test: verify connectors with deterministic fixtures`
7. `docs: document provider capabilities and limitations`

Demo: request equivalent indicator metadata and normalized observations from two fixture providers without exposing their original response formats to the rest of the application.

## Phase 4: Add versioned dataset recipes and build planning

**Status:** complete.

**Goal:** turn a research question into a validated, immutable build plan.

Delivered:

- Dataset recipe, recipe-version, variable, and transformation schema.
- Recipe YAML/JSON import and export.
- Draft validation and immutable version freezing.
- Provider input resolution.
- Deterministic build identity.
- Build-run and build-input records.
- Recipe and build API endpoints.
- Migration and repository tests.

Implementation notes:

- Unknown recipe fields are rejected rather than silently ignored.
- Recipe drafts are editable; frozen versions are immutable and numbered.
- Freezing identical content reuses the existing content-addressed version.
- Variables and transformation declarations retain stable order.
- Provider resolution happens outside database transactions.
- A build identity includes frozen recipe content, planner version, resolved requests, and normalized indicator metadata.
- Replanning identical inputs reuses the existing planned build.
- Plans do not yet retrieve or transform observations; that begins in Phase 5.

Likely commits:

1. `feat: model dataset recipes and immutable versions`
2. `feat: validate variables entities dates and join rules`
3. `feat: import and export recipe YAML`
4. `feat: resolve provider inputs for recipe versions`
5. `feat: create deterministic build plans`
6. `feat: expose recipe and build APIs`
7. `test: verify recipe versioning and build identity`

Demo: create the European macro-panel recipe, validate it, freeze a version, and inspect its resolved provider requests.

## Phase 5: Build the harmonization and transformation engine

**Status:** complete.

**Goal:** turn normalized provider inputs into one correct research table.

Delivered:

- Polars or DuckDB execution engine.
- Canonical entity and period representations.
- Versioned country-code mappings.
- Long-form normalized staging data.
- Explicit rename, filter, lag, difference, percent-change, scaling, and aggregation operations.
- Frequency conversion with rejection of ambiguous cases.
- Outer/inner join rules with unmatched-key reporting.
- Stable column types and ordering.
- Bounded data preview.

Implementation notes:

- Polars values use `Decimal(30, 10)` through staging and transformation.
- Entity aliases are explicit and carry mapping version `2026-11-04.v1`.
- Provider periods become canonical period-start dates.
- Recipe entity/date selection performs deterministic filtering and output names perform renaming.
- Coarser frequency conversion requires an explicit aggregate method; upsampling is rejected.
- Lag, difference, percent change, and scale execute in declared order with documented nulls.
- Joins report left-only and right-only key counts before applying outer, inner, or left behavior.
- Execution advances a build to `validating`; Phase 6 owns validation and final success.
- Stored previews are capped at 1,000 rows and retain the full result row count.

Likely commits:

1. `build: add analytical dataframe engine`
2. `feat: harmonize entity and period identifiers`
3. `feat: execute deterministic transformation steps`
4. `feat: add explicit frequency conversion rules`
5. `feat: join variables with unmatched-key reporting`
6. `feat: expose bounded build previews`
7. `test: cover transformations joins and null semantics`

Demo: combine FRED and World Bank fixtures into one four-country annual panel and explain every unmatched row.

## Phase 6: Add validation, provenance, and export bundles

**Status:** complete.

**Goal:** deliver the first genuinely useful local product.

Delivered:

- Coverage, duplicate-key, type, range, and missing-value validation.
- Recipe-defined warning and error rules.
- Source-to-output column lineage.
- Canonical dataset serialization and SHA-256 checksum.
- CSV and Parquet exports.
- Generated codebook and provider citations.
- Machine-readable manifest.
- Human-readable validation report.
- Rebuild comparison showing changed inputs and outputs.
- End-to-end fixture build.

Implementation notes:

- Validation findings have `info`, `warning`, or blocking `error` severity.
- A build with blocking findings stores its report and fails without publishing a bundle.
- The dataset checksum covers canonical logical rows rather than format-specific bytes.
- Every artifact carries a SHA-256 checksum; downloads verify it before serving the file.
- The manifest captures build identity, recipe hash, software and mapping versions, schema, input fingerprints, validation summary, and artifact metadata.
- Validation, lineage, exports, and final success are persisted in one short database transaction after files exist.
- Rebuild comparison distinguishes recipe/input changes from logical output changes.
- The checked-in sample uses deterministic provider fixtures, not claims about current live values.

Likely commits:

1. `feat: validate coverage keys types and ranges`
2. `feat: record source-to-output lineage`
3. `feat: export deterministic CSV and Parquet`
4. `feat: generate codebook manifest and citations`
5. `feat: compare dataset rebuilds`
6. `test: verify reproducible end-to-end builds`
7. `docs: publish complete research dataset example`

Demo:

```text
recipe
→ provider fixtures
→ harmonized panel
→ validation report
→ data.csv + data.parquet
→ codebook + manifest + citations
→ repeat build with identical checksum
```

**Local product MVP:** release `v0.1.0`.

**Portfolio checkpoint:** record the full workflow and publish a sample research bundle.

## Phase 7: Add multi-user workflows and asynchronous builds

**Status:** in progress.

**Goal:** make long-running builds safe and usable as a hosted application.

Delivered so far:

- Researcher registration, login, logout, and current-account endpoints.
- Memory-hard salted password hashing without storing plaintext credentials.
- Opaque HTTP-only browser sessions with hashed token storage, expiry, and revocation.
- Owner foreign keys on recipes and builds, with inherited protection for versions and outputs.
- Authenticated access on every private research and artifact route.
- Not-found behavior that does not disclose another user's resource existence.
- OpenAPI cookie-security documentation and two-user PostgreSQL isolation coverage.
- Atomic execution claims that prevent two requests from running the same attempt.
- Terminal successful and failed builds that cannot be executed or overwritten again.
- Explicit failed-build retry as a new numbered build ID and artifact directory.
- Migrations `0005` through `0007` with PostgreSQL lifecycle, ownership, and attempt coverage.

Deliverables:

- Authentication and recipe/build ownership. **Complete.**
- Immutable numbered build attempts and terminal-state enforcement. **Complete.**
- Background build queue and workers.
- Job progress and cancellation policy.
- Idempotent job handling and terminal failure states.
- Provider input cache and refresh policies.
- Authorized artifact downloads.
- Small browser interface for recipe creation, build status, preview, validation, and exports.
- Audit history and per-user limits.

Likely commits:

1. `feat: add authenticated users and ownership`
2. `feat: queue dataset builds outside API requests`
3. `feat: report progress failures and retries`
4. `feat: cache provider inputs by policy`
5. `feat: authorize export downloads`
6. `feat: add research build workflow UI`
7. `test: cover isolation duplicate delivery and failure recovery`

Demo: two users create builds concurrently without viewing each other's private recipes or exports.

## Phase 8: Deploy and operate on AWS

**Goal:** run the product reliably in the cloud.

Deliverables:

- Infrastructure as code.
- API and worker images in ECR.
- ECS Fargate API and build workers.
- RDS PostgreSQL with backups.
- SQS build queue and dead-letter queue.
- S3 artifact storage with authorized access.
- Secrets Manager provider credentials.
- CloudWatch logs, metrics, dashboards, and alarms.
- GitHub Actions deployment workflow.
- Recovery, replay, cost, and operational runbooks.

Likely commits:

1. `infra: provision network database storage queues and secrets`
2. `infra: deploy API and build worker services`
3. `feat: store and authorize S3 research artifacts`
4. `ops: add metrics alarms backups and runbooks`
5. `ci: automate production deployment`
6. `docs: publish production architecture and live demo`

Demo: submit a real build, watch asynchronous progress, and download a verified export bundle from the deployed service.

**Production milestone:** tag `v1.0.0`.

## Phase 9: Optional extensions

Only begin after the core workflow is reliable:

- OECD, Eurostat, BLS, or BEA connectors.
- ALFRED point-in-time and vintage-aware recipes.
- Research-dataset comparison dashboard.
- Collaboration and public recipe templates.
- Scheduled refreshes.
- AI-assisted indicator search and draft recipe creation.
- Natural-language explanations of validation and lineage.

AI remains an assistant. The approved recipe, connector responses, deterministic engine, and provenance records remain authoritative.

## Milestones and Git workflow

| Point | Result | Suggested tag |
|---|---|---|
| Phase 3 | Two-provider normalized connector layer | optional `v0.0.3` |
| Phase 4 | Versioned recipe and build planner | optional `v0.0.4` |
| Phase 6 | Complete local research-data MVP | `v0.1.0` |
| Phase 8 | Secure deployed production product | `v1.0.0` |

Commit after every meaningful, tested change. Push after completed features or work sessions. Milestones are for demonstrations and releases, not giant commits.
