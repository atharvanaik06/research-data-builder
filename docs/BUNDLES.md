# Validation and Research Bundles

Phase 6 turns a transformed table into a result a researcher can inspect, cite, share, and rebuild. It also makes `succeeded` a meaningful state: the dataset passed blocking checks and every required artifact was produced and recorded.

## Validation boundary

The validation engine checks:

- duplicate entity-period keys;
- stable key and variable column order;
- decimal variable types;
- expected entity-period coverage;
- missing values by variable;
- recipe-defined numeric ranges;
- unmatched join keys reported by execution.

Findings have `info`, `warning`, or `error` severity. Warnings remain visible but allow export. An error prevents export, persists the validation report, and moves the build to `failed`.

## Immutable attempts

Only a `planned` build can be claimed for execution. The claim is an atomic database update, so two requests cannot both begin the same attempt. `succeeded` and `failed` are terminal: executing either again returns a conflict and output persistence refuses to replace existing records.

A temporary failure is retried explicitly:

```text
POST /api/v1/builds/{failed_build_id}/retry
```

The retry receives a new build ID, increments `attempt_number`, copies the frozen plan and resolved inputs, and writes to its own future artifact directory. The failed attempt remains available as historical evidence.

## Bundle contents

Each successful build receives its own directory below the configured artifact root:

| File | Purpose |
|---|---|
| `data.csv` | Human-readable rectangular dataset when requested by the recipe. |
| `data.parquet` | Typed, compressed analytical dataset when requested. |
| `recipe.yaml` | Exact frozen research definition. |
| `validation.json` | Machine-readable checks and summary. |
| `validation.md` | Short human-readable validation report. |
| `codebook.json` | Column types, roles, sources, units, and missing counts. |
| `citations.md` | Provider, indicator, and source links. |
| `lineage.json` | Source request and ordered transformations for every output variable. |
| `manifest.json` | Build identity, versions, schema, checksum, and artifact inventory. |
| `checksums.sha256` | File-level integrity checks for the bundle. |

The logical dataset checksum is computed from canonical rows and values, so it answers whether two builds produced the same research table independent of CSV or Parquet encoding. File checksums answer whether an individual artifact's bytes changed or became corrupted.

## Inspecting a build

The API exposes the bounded preview separately from the potentially large files:

```text
GET /api/v1/builds/{build_id}
POST /api/v1/builds/{failed_build_id}/retry
GET /api/v1/builds/{build_id}/preview
GET /api/v1/builds/{build_id}/validation
GET /api/v1/builds/{build_id}/lineage
GET /api/v1/builds/{build_id}/exports
GET /api/v1/exports/{export_id}/download
GET /api/v1/builds/{build_id}/comparison?other_build_id={other_build_id}
```

Downloads are restricted to the configured artifact root and checked against the stored SHA-256 checksum before being served.

## Rebuild comparison

Comparison reports separately identify changes to:

- the frozen recipe content;
- resolved provider input fingerprints;
- the final logical dataset checksum.

This distinction helps answer whether a result changed because the research instructions changed, upstream data changed, or both. Full observation-level vintage explanations remain a later extension.

## Demonstration bundle

`examples/sample_bundle` is generated entirely from deterministic World Bank-shaped fixtures. It demonstrates the complete artifact contract without requiring credentials or relying on live APIs. The values are demonstration data and should not be described as a current economic release.
