# Recipe Versions and Build Planning

Phase 4 turns a research definition into a validated, immutable, deterministic plan. Phase 5 now
executes that plan into a bounded research-table preview.

## Recipe shape

```yaml
name: European macro panel
description: Annual GDP growth and inflation inputs
entities: [CZE, DEU, FRA, POL]
start_date: 2000-01-01
end_date: 2025-12-31
variables:
  - provider: world_bank
    indicator_id: NY.GDP.MKTP.KD.ZG
    output_name: gdp_growth
  - provider: world_bank
    indicator_id: FP.CPI.TOTL.ZG
    output_name: inflation
output_frequency: annual
transformations:
  - operation: lag
    variable: inflation
    parameters:
      periods: 1
join:
  type: outer
  keys: [entity, period]
missing_values: preserve
formats: [csv, parquet]
```

Unknown fields are errors. Output names must use lower-case snake case. Dates, entities, output
names, formats, join keys, and transformation references are validated together.

The reviewed transformation vocabulary describes `aggregate`, `lag`, `difference`,
`percent_change`, and `scale`. Date/entity selection performs explicit filtering and each variable's
`output_name` performs the provider-to-output rename.

## Draft and version behavior

```text
editable draft
    │ validate
    ▼
canonical JSON + SHA-256
    │ freeze
    ▼
immutable recipe version 1
```

Changing a draft never changes an existing version. Freezing new semantic content creates the next
version number. Freezing identical content returns the existing version, preventing meaningless
duplicates.

JSON and YAML are presentation formats for the same strict model. Their canonical semantic content
produces the same hash.

## Build planning

For each variable, the planner:

1. selects the configured provider connector;
2. resolves exact indicator metadata;
3. creates a normalized request with indicator, entities, and dates;
4. fingerprints the normalized indicator metadata;
5. combines ordered inputs with the frozen recipe hash and planner version;
6. calculates the deterministic build identity.

Planning performs provider calls without holding a database transaction open. A short transaction
then stores the plan and inputs. Repeating the same resolved plan returns the existing build.

The identity means:

```text
same frozen recipe + same resolved requests + same metadata + same planner
                             = same planned build
```

An exact observation-level identity is not claimed yet. Retrieval and source-version identities are
added while executing the plan in the next phases.

## API routes

| Method and route | Result |
|---|---|
| `POST /api/v1/recipes` | Create a validated draft. |
| `POST /api/v1/recipes/import?format=yaml` | Import JSON or YAML text. |
| `GET /api/v1/recipes` | List drafts. |
| `GET /api/v1/recipes/{id}` | Inspect one draft. |
| `PUT /api/v1/recipes/{id}/draft` | Replace a draft after validation. |
| `POST /api/v1/recipes/{id}/versions` | Freeze or reuse immutable content. |
| `GET /api/v1/recipes/{id}/versions` | List numbered versions. |
| `GET /api/v1/recipe-versions/{id}` | Inspect frozen content. |
| `GET /api/v1/recipe-versions/{id}/export` | Export JSON or YAML. |
| `POST /api/v1/recipe-versions/{id}/builds` | Resolve or reuse a deterministic plan. |
| `GET /api/v1/builds/{id}` | Inspect build status, identity, and resolved inputs. |
| `POST /api/v1/builds/{id}/execute` | Retrieve, harmonize, transform, and join inputs. |
| `POST /api/v1/builds/{id}/retry` | Create a new numbered attempt from a failed build. |
| `GET /api/v1/builds/{id}/preview` | Read the stored bounded table preview. |

FRED build planning requires a configured API key. World Bank planning is keyless. A provider
configuration failure is reported separately from a missing or invalid provider indicator.
