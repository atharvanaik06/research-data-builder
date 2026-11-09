# Research Data Builder Product Requirements

## 1. Product summary

Research Data Builder retrieves structured data from supported public APIs, harmonizes it into a common research schema, validates the result, and exports a reproducible dataset bundle.

The product does not attempt to support every possible dataset. Its initial scope is public economic and social time-series data available through FRED and World Bank APIs.

Its value is the work around downloading:

- combining several providers;
- normalizing indicators, entities, dates, units, and frequencies;
- making transformations explicit;
- identifying missing or suspicious coverage;
- recording exact input versions and build decisions;
- generating research-ready data and documentation together;
- rebuilding the same dataset later.

## 2. Problem, simplified

A researcher wants an annual panel containing GDP growth, inflation, and unemployment for several countries from 2000 through 2025.

Without the product, the researcher must locate indicators, call or download from several sources, normalize country identifiers, interpret units, reshape responses, align dates, join tables, inspect missing values, document sources, and write the process again when data changes.

With Research Data Builder, the researcher saves a recipe:

```yaml
name: european_macro_panel
entities: [CZE, DEU, FRA, POL]
start_date: 2000-01-01
end_date: 2025-12-31
variables:
  - provider: world_bank
    indicator: NY.GDP.MKTP.KD.ZG
    name: gdp_growth
  - provider: world_bank
    indicator: FP.CPI.TOTL.ZG
    name: inflation
output_frequency: annual
formats: [csv, parquet]
```

One deterministic build produces data, documentation, validation, provenance, and checksums.

## 3. Target users

### Primary: economics students and researchers

- Assemble multi-series or multi-country datasets faster.
- Understand exactly which source indicators and transformations were used.
- Share a reproducible recipe rather than an unexplained spreadsheet.

### Secondary: analysts and data teams

- Refresh recurring public-data datasets.
- Detect upstream changes and coverage problems.
- Reuse standardized provider connectors and transformations.

### Later: instructors and research collaborators

- Review student data preparation.
- Reproduce a collaborator's build.
- Compare dataset versions over time.

## 4. Product MVP user stories

1. As a researcher, I can search supported provider indicators.
2. As a researcher, I can select variables, entities, and a time range.
3. As a researcher, I can inspect source units, frequencies, and descriptions before building.
4. As a researcher, I can save a versioned dataset recipe in my private account.
5. As a researcher, I can build the recipe using deterministic transformations.
6. As a researcher, I can preview the joined research table.
7. As a researcher, I can see missing coverage and validation warnings.
8. As a researcher, I can export CSV and Parquet data.
9. As a researcher, I receive a codebook, source manifest, citations, and checksum.
10. As a collaborator, I can rebuild the same recipe and verify whether its inputs changed.
11. As a researcher, I can run the workflow from a browser.
12. As a researcher, I can view job progress, cancel work, and retry a failed build.
13. As a researcher, I can view my recent activity.

## 5. Functional requirements

### FR-1: Provider connector contract

- Define one interface for provider metadata search, indicator retrieval, and observation retrieval.
- Keep provider response models outside the build engine.
- Normalize provider errors into stable application categories.
- Support explicit timeouts, bounded retries, pagination, and rate-limit handling.
- Begin with FRED and World Bank implementations.

### FR-2: Provider catalog and discovery

- Store provider, indicator ID, title, description, units, frequency, and entity dimensions.
- Search indicators by ID or text.
- Display source metadata before a variable is added to a recipe.
- Refresh metadata without creating duplicate indicators.

### FR-3: Normalized observations

- Convert provider responses into a common observation model.
- Preserve provider identity, indicator ID, entity, period, value, units, retrieval time, and available source-version fields.
- Use decimal-safe numeric values.
- Represent missing observations explicitly.
- Preserve repeated source versions instead of silently overwriting them.

### FR-4: Dataset recipes

- Create, read, update, and version recipes.
- Specify providers, indicators, variable names, entities, date ranges, frequency, transformations, join rules, and missing-value policy.
- Validate recipes before execution.
- Freeze a recipe version when a build starts.
- Store recipes as structured data and allow YAML/JSON import and export.

### FR-5: Build orchestration

- Create an auditable build run from one recipe version.
- Resolve and retrieve required provider inputs.
- Reuse suitable cached inputs when the recipe permits it.
- Record running, successful, and failed build states.
- Prevent duplicate builds for the same deterministic input identity.
- Never mark a build successful if required exports or provenance are incomplete.

### FR-6: Harmonization

- Normalize supported country/entity identifiers to a documented canonical code.
- Normalize period representations.
- Convert provider response shapes to tidy long-form observations.
- Support explicit frequency conversion rules.
- Reject ambiguous automatic conversions.
- Preserve source units and record every applied conversion.

### FR-7: Transformations

- Support a small reviewed transformation set such as rename, filter, lag, difference, percent change, annual aggregation, and unit scaling.
- Apply transformations in declared order.
- Avoid arbitrary user code in the MVP.
- Record transformation parameters and engine version.
- Produce the same logical output for the same inputs and recipe.

### FR-8: Join and output construction

- Join variables on explicit entity and period keys.
- Report unmatched rows instead of silently dropping them.
- Support long and wide output layouts.
- Preserve stable column ordering and types.
- Produce a preview before final export.

### FR-9: Validation

- Measure expected versus observed entity-period coverage.
- Report missing values, duplicate keys, unexpected types, and invalid ranges.
- Allow recipe-defined validation rules.
- Distinguish warnings from build-blocking errors.
- Store validation results with the build.

### FR-10: Reproducibility and provenance

- Record recipe version, provider requests, retrieved input versions, transformations, software version, and build timestamps.
- Generate deterministic checksums for canonical logical content.
- Explain the source and transformation lineage of every output variable.
- Rebuild a historical recipe and report changed upstream inputs.

### FR-11: Export bundle

- Export CSV and Parquet.
- Generate a machine-readable manifest.
- Generate a human-readable codebook.
- Generate provider citations or citation guidance.
- Package validation results and checksum with the export.
- Store large artifacts outside PostgreSQL while retaining their metadata and location.

### FR-12: Authentication and collaboration

- Users must sign in before they access recipes, builds, activity, or exports.
- Users may access only their own private recipes, builds, credentials, and exports.
- The system must enforce bounded recipe sizes and outstanding build counts.
- A later collaboration model may support shared read or build permissions.

### FR-13: AI assistance

AI-assisted indicator discovery and recipe drafting are optional later features. The deterministic recipe and build engine remain the authority. An AI suggestion must never silently select sources, transformations, or missing-value policies.

## 6. Proposed API surface

```text
GET    /health
GET    /ready

GET    /api/v1/providers
GET    /api/v1/providers/{provider_id}/indicators
GET    /api/v1/providers/{provider_id}/indicators/{indicator_id}

POST   /api/v1/recipes
GET    /api/v1/recipes
GET    /api/v1/recipes/{recipe_id}
PUT    /api/v1/recipes/{recipe_id}/draft
POST   /api/v1/recipes/import
POST   /api/v1/recipes/{recipe_id}/versions
GET    /api/v1/recipes/{recipe_id}/versions
GET    /api/v1/recipe-versions/{version_id}
GET    /api/v1/recipe-versions/{version_id}/export

POST   /api/v1/recipe-versions/{version_id}/builds
GET    /api/v1/builds/{build_id}
GET    /api/v1/builds/{build_id}/preview
GET    /api/v1/builds/{build_id}/validation
GET    /api/v1/builds/{build_id}/lineage
GET    /api/v1/builds/{build_id}/exports
```

## 7. Conceptual data model

Already implemented foundation:

- `series`: provider indicator metadata.
- `sync_runs`: provider retrieval audit records.
- `observation_versions`: append-only normalized provider values.
- `change_events`: changes between provider input versions.

Planned product records:

- `providers`: connector capabilities and configuration.
- `dataset_recipes`: user-facing dataset definitions.
- `recipe_versions`: immutable recipe snapshots.
- `recipe_variables`: selected provider indicators and output names.
- `build_runs`: execution status, identity, timing, and summary.
- `build_inputs`: exact source versions used.
- `transformation_steps`: ordered deterministic operations.
- `validation_results`: coverage, warning, and error records.
- `exports`: format, location, row count, schema, and checksum.
- `users` and ownership records before public deployment.

Large raw responses and generated files may be stored as local files in the MVP and object storage in production. PostgreSQL stores their identity, metadata, lineage, and checksum.

## 8. Non-functional requirements

### Correctness

- Use `Decimal` and PostgreSQL `NUMERIC` for numeric source values.
- Never perform an undocumented conversion.
- Make join keys and frequency rules explicit.
- Preserve source metadata and missing values.

### Determinism and reproducibility

- Identical recipe, input versions, and engine version produce identical canonical output.
- Generated manifests use stable ordering and serialization.
- Checksums exclude non-deterministic presentation fields.

### Consistency

- Build status, input lineage, validation, and export metadata transition atomically where possible.
- Failed artifact creation must not produce a successful build.
- Database constraints provide final duplicate protection.

### Reliability

- Provider calls use timeouts and bounded retries.
- Previously stored inputs and exports remain available during provider outages.
- Retried jobs do not create duplicate logical builds.

### Performance and scale

- Stream or batch large provider results.
- Avoid loading unbounded datasets into API-process memory.
- Use Polars or DuckDB for analytical transformations.
- Keep PostgreSQL focused on metadata, lineage, version history, and transactional state.

### Security

- Provider credentials and database passwords remain outside source control.
- Validate recipe sizes, provider parameters, filenames, and export paths.
- Public deployment enforces authentication, authorization, TLS, and rate limits.

### Observability

- Structured logs connect request, recipe version, build, provider retrieval, validation, and export IDs.
- Metrics include provider latency, build duration, rows processed, cache reuse, validation failures, and export failures.

### Maintainability and testability

- Provider connectors implement one contract.
- Transformations are small deterministic functions.
- CI runs against recorded fixtures rather than relying on live APIs.
- PostgreSQL migrations are checked for schema drift and round-trip behavior.

## 9. Local MVP acceptance criteria

The product MVP is complete when a reviewer can:

1. start the API, PostgreSQL, and local build worker;
2. discover indicators from FRED and World Bank fixtures;
3. create a recipe containing at least three variables and four countries;
4. validate and freeze the recipe;
5. build a joined annual panel deterministically;
6. inspect missing coverage and unmatched joins;
7. export CSV and Parquet;
8. open the generated codebook, manifest, citations, and validation report;
9. rebuild from the same inputs and receive the same checksum;
10. change a source fixture and see the input and output differences reported;
11. run the complete automated test suite successfully.

## 10. Out of scope for the local MVP

- Arbitrary websites, PDFs, images, and proprietary databases.
- Survey microdata and row-level confidential data.
- Arbitrary user-submitted Python code.
- Statistical modeling or causal inference.
- Automatic imputation without an explicit recipe rule.
- A universal ontology for every research discipline.
- More than the initial supported providers.
- AI-generated builds without human review.
- Full point-in-time backtesting.

## 11. Success measures

- A documented example dataset can be built from a clean clone.
- Repeating an identical build yields the same checksum.
- Every output variable has source and transformation lineage.
- Duplicate entity-period keys are either resolved by an explicit rule or block the build.
- Missing coverage is visible rather than silently removed.
- A researcher can refresh a saved recipe without rewriting collection and cleaning code.
