# Harmonization and Transformation Engine

Phase 5 executes a frozen recipe and resolved provider plan into one stable research table using
Polars. It produces a bounded preview and an execution report; Phase 6 adds final validation and
exports.

## Execution flow

```text
resolved provider requests
→ normalized observations
→ canonical entity + period + Decimal value
→ long-form variable tables
→ explicit frequency aggregation
→ ordered transformations
→ explicit joins + unmatched-key report
→ stable wide table
→ bounded stored preview
```

Provider calls and dataframe work happen outside database transactions. Short transactions record
`retrieving`, the execution result, or a sanitized failure.

## Canonical staging schema

Every variable enters the engine as:

| Column | Type | Meaning |
|---|---|---|
| `entity` | string or null | Canonical ISO3-like code; null for entity-free series. |
| `period` | date | Canonical period-start date. |
| `variable` | string | Recipe output name. |
| `value` | `Decimal(30, 10)` or null | Provider value without binary float conversion. |

Duplicate entity-period-variable keys are rejected. Missing values remain null.

Entity aliases are explicit and versioned as `2026-11-04.v1`. Unrecognized names are rejected
instead of guessed. Annual, semiannual, quarterly, and monthly periods use their period start;
daily, weekly, and irregular observations preserve their source date.

## Frequency safety

No implicit frequency conversion occurs.

```text
same frequency                       → accepted without aggregation
finer source → coarser output        → requires mean/sum/min/max/last
coarser source → finer output        → rejected
unknown or unsupported conversion    → rejected
```

All-null groups remain null, including `sum`, so missing research data cannot become a misleading
zero.

## Transformations

Operations execute in recipe order:

- `aggregate`: explicit coarser-frequency method;
- `lag`: shift within each entity;
- `difference`: current minus lagged value;
- `percent_change`: percentage change with null for missing or zero denominator;
- `scale`: multiply by a declared non-zero factor.

Date/entity selection supplies filtering. `output_name` supplies deterministic renaming. Lag-based
operations produce leading nulls rather than silently removing rows.

## Joins

Variables join only on declared keys: `entity + period` or `period`. Outer, inner, and left joins
are supported. Before each join the engine counts keys found only on the accumulated left table and
only on the incoming right table.

The report answers questions such as:

```text
GDP has CZE 2024, but inflation does not.
Inflation has FRA 2024, but GDP does not.
```

Column order follows recipe variable order, and rows sort by declared join keys.

## Preview boundary

`POST /api/v1/builds/{id}/execute` queues the workflow and returns `202 Accepted`. The worker runs the workflow. The stored preview
contains at most 1,000 rows, JSON-safe ISO dates and decimal strings, the complete column list, full
row count, and a truncation flag.

The full in-memory dataframe is not stored as JSON. Phase 6 serializes canonical CSV and Parquet
artifacts, records their checksums, and moves the build from `validating` toward success.
