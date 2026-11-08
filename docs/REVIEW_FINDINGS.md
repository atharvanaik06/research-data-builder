# Adversarial Review Findings and Engineering Openings

**Review date:** 2026-11-07  
**Reviewed commit:** `b58ff29`  
**Status:** Open engineering backlog; no findings in this document were fixed during the review.

This document records failure cases discovered while testing the Phase 6 local MVP and the first Phase 7 authentication slice. It distinguishes confirmed defects from incomplete roadmap work and gives us a durable checklist for future phases.

## Verification baseline

The ordinary project gates were healthy at the time of review:

- Ruff formatting and linting passed.
- Strict Mypy checks passed.
- 99 local tests passed; three PostgreSQL tests were skipped because no local test database was configured.
- The latest GitHub Actions run passed all 102 tests with PostgreSQL.
- Coverage was 91.26%.
- Alembic compiled through migration `0006`.
- The Git working tree was clean.
- Docker and Compose could not be rerun locally because Docker was not installed on the review machine.

The findings below demonstrate that high line and branch coverage does not yet cover important combinations of valid recipe options, concurrent requests, process failures, or hosted security boundaries.

## Severity definitions

| Severity | Meaning |
|---|---|
| P0 | Blocks any public deployment because it can expose or corrupt user research. |
| P1 | Can silently produce incorrect research output, destroy reproducibility, or strand builds. |
| P2 | Important reliability, scalability, security-hardening, or product-completeness gap. |
| P3 | Documentation, maintenance, or lower-risk operational issue. |

## Confirmed findings

### RDB-001 — Research endpoints were not authenticated or authorized

**Severity:** P0  
**Type:** Phase 7 deployment blocker
**Status:** Resolved

Every private research route now uses the authenticated-user boundary. Recipes and builds have non-null owners; versions, validation, lineage, comparison, exports, execution, and downloads derive authorization through those owned records.

Repository lookups include the current owner and return not found for another user's IDs. The generated OpenAPI document advertises the browser-session cookie on private operations. PostgreSQL integration coverage proves that two users can build identical recipe content without seeing each other's recipes, versions, builds, or exports.

An anonymous caller is stopped before database access:

```text
request private route
→ no valid browser session
→ 401 Unauthorized
```

Relevant code:

- `src/research_data_builder/api/recipes.py`
- `src/research_data_builder/auth/dependencies.py`
- `docs/AUTHENTICATION.md`

Resolution checklist:

- [x] Add an owner foreign key to recipes.
- [x] Derive version, build, validation, lineage, comparison, and export access through owned recipes.
- [x] Apply the authenticated-user dependency to every private route.
- [x] Return `404` rather than revealing whether another user's resource exists.
- [x] Add two-user isolation tests across the repository access boundary.
- [x] Add an OpenAPI cookie security scheme.

### RDB-002 — A successful build can be rerun and overwritten

**Severity:** P0  
**Type:** Reproducibility defect  
**Status:** Open

The execute endpoint accepts any existing build state. `mark_retrieving()` does not verify the current state, export writes back into the same build directory, and successful output persistence deletes and replaces earlier validation, lineage, and export records.

Reproduction:

```text
Same build ID, first dataset checksum:
102f72d6bf8577326f40944b10db679bfbceb02ec775e270e0560bbf76e8c5f7

Same build ID, second dataset checksum:
6267d608da194ddc003e89cb99cd9b369d094e4ec5d0a3888e7ee4b9fe2b01a4

Final data.csv contained only the second value.
```

Relevant code:

- `src/research_data_builder/api/recipes.py`
- `src/research_data_builder/db/build_repositories.py`
- `src/research_data_builder/db/output_repositories.py`
- `src/research_data_builder/artifacts/exporter.py`

Resolution checklist:

- [ ] Make `succeeded` builds immutable.
- [ ] Define explicit legal build-state transitions.
- [ ] Reject execution unless the build is in an allowed starting state.
- [ ] Represent a refresh or retry as a new attempt or build record.
- [ ] Include exact retrieved input identity in the immutable build identity.
- [ ] Add regression tests proving historical bundles cannot change.

### RDB-003 — Declared transformation order is not respected

**Severity:** P1  
**Type:** Silent research-correctness defect  
**Status:** Open

Frequency aggregation always runs before other transformations, regardless of where `aggregate` appears in the recipe. A syntactically valid recipe can therefore answer a different question from the one it declares.

Tested recipe order:

```text
monthly percent change
→ annual mean
```

Observed results:

```text
Declared-order result for 2023: 10.0000000000
Current engine result for 2023: 15.5000000000
```

The current engine calculated the annual mean first and then calculated annual percent change.

Relevant code:

- `src/research_data_builder/engine/executor.py`
- `src/research_data_builder/engine/frequency.py`
- `src/research_data_builder/engine/transform.py`

Resolution checklist:

- [ ] Compile transformations into one explicitly ordered execution plan.
- [ ] Either execute aggregation at its declared position or require it to appear in one documented position.
- [ ] Reject mathematically ambiguous sequences.
- [ ] Add non-commutative ordering tests such as percent-change-before-mean.
- [ ] Record the compiled operation order in lineage.

### RDB-004 — The `drop_rows` missing-value policy is ignored

**Severity:** P1  
**Type:** Recipe-contract defect  
**Status:** Open

Recipes accept `missing_values: drop_rows`, but the executor never reads or applies the setting.

Reproduction:

```text
Recipe policy: drop_rows
Output height: 1
Output null count: 1
```

Relevant code:

- `src/research_data_builder/recipes/schemas.py`
- `src/research_data_builder/engine/executor.py`
- `src/research_data_builder/validation/engine.py`

Resolution checklist:

- [ ] Apply the policy at a documented point after joins and transformations.
- [ ] Define whether a row is dropped for any missing variable or only selected variables.
- [ ] Report dropped-row counts in validation and lineage.
- [ ] Add preserve-versus-drop integration tests.

### RDB-005 — Unexpected failures leave builds permanently `retrieving`

**Severity:** P1  
**Type:** Lifecycle and recovery defect  
**Status:** Open

The execution endpoint catches a limited group of expected exceptions. A connector `RuntimeError`, process termination, Polars defect, or other unexpected failure escapes after the build has been marked `retrieving`.

Reproduction:

```text
Escaped exception: unexpected connector defect
Final persisted/in-memory state: retrieving
```

Relevant code:

- `src/research_data_builder/api/recipes.py`
- `src/research_data_builder/db/build_repositories.py`

Resolution checklist:

- [ ] Put build execution behind a durable worker boundary.
- [ ] Record terminal failure for unexpected exceptions without leaking internals.
- [ ] Track worker heartbeat and attempt timestamps.
- [ ] Recover or fail stale in-progress builds.
- [ ] Add process-loss and unexpected-exception tests.

### RDB-006 — Partial-period date ranges discard valid observations

**Severity:** P1  
**Type:** Date-semantics defect  
**Status:** Open

Provider observations are normalized to period-start dates before filtering. A request from `2023-07-01` through `2023-12-31` normalizes the annual 2023 observation to `2023-01-01` and then removes it as out of range. Validation simultaneously expects the `2023-01-01` key.

Reproduction:

```text
Rows retained after bounding: 0
Expected validation key: CZE / 2023-01-01
```

Relevant code:

- `src/research_data_builder/engine/harmonize.py`
- `src/research_data_builder/engine/executor.py`
- `src/research_data_builder/validation/engine.py`

Resolution checklist:

- [ ] Choose and document period-inclusion semantics.
- [ ] Normalize recipe boundaries to output periods before provider requests and filtering, or reject unaligned dates.
- [ ] Use the same period function for execution and validation.
- [ ] Test partial annual, quarterly, and monthly ranges.

### RDB-007 — Supported entity aliases are filtered out after normalization

**Severity:** P1  
**Type:** Entity-semantics defect  
**Status:** Open

The harmonization layer accepts aliases such as `CZ → CZE`. Provider output becomes `CZE`, but geographic filtering still compares it with the original recipe value `CZ`, removing the requested observation.

Relevant code:

- `src/research_data_builder/engine/harmonize.py`
- `src/research_data_builder/engine/executor.py`
- `src/research_data_builder/recipes/planner.py`

Resolution checklist:

- [ ] Canonicalize entities when the recipe is validated or frozen.
- [ ] Use canonical entities consistently for requests, filters, coverage, lineage, and build identity.
- [ ] Record original user input only as optional display metadata.
- [ ] Add alias-to-canonical end-to-end tests.

### RDB-008 — Mixed FRED and multi-country World Bank panels fail validation

**Severity:** P1  
**Type:** Cross-provider design defect  
**Status:** Open

Recipes containing FRED are required to use period-only joins because FRED lacks an entity dimension. A multi-country World Bank frame then loses its entity key, producing multiple rows with the same period. Validation rejects the result as duplicate keys.

Reproduction:

```text
2023-01-01 / FRED rate 5.0 / CZE GDP 1.0
2023-01-01 / FRED rate 5.0 / DEU GDP 2.0

Validation: FAILED
Finding: dataset contains 1 duplicate key group
```

Relevant code:

- `src/research_data_builder/recipes/schemas.py`
- `src/research_data_builder/engine/join.py`
- `src/research_data_builder/validation/engine.py`

Resolution checklist:

- [ ] Define whether entity-free series broadcast across countries.
- [ ] Preserve the World Bank entity key in the final output.
- [ ] Encode broadcast behavior explicitly rather than through a period-only join.
- [ ] Reject unsupported mixed-dimensional recipes before execution.
- [ ] Add a FRED-plus-two-country World Bank end-to-end test.

### RDB-009 — Build and recipe creation contain check-then-insert races

**Severity:** P1  
**Type:** Concurrency defect  
**Status:** Open

Deterministic build creation first queries by identity and then inserts. Concurrent requests can both observe no row and race against the unique constraint. Recipe version numbering similarly reads the current maximum and then inserts the next number.

Concurrent execution also lacks row locking or compare-and-set transitions, allowing multiple requests to write the same artifact directory and replace the same output metadata.

Relevant code:

- `src/research_data_builder/db/build_repositories.py`
- `src/research_data_builder/db/recipe_repositories.py`
- `src/research_data_builder/db/output_repositories.py`

Resolution checklist:

- [ ] Recover from unique-conflict races by loading the winning row.
- [ ] Use row locks or atomic conditional updates for state transitions.
- [ ] Ensure at most one active attempt per build identity and user.
- [ ] Add concurrent freeze, plan, and execute PostgreSQL tests.

### RDB-010 — Password hashing parameters are below current OWASP guidance

**Severity:** P2  
**Type:** Authentication hardening  
**Status:** Open

The project uses scrypt with `N=2^14, r=8, p=1`. OWASP's equivalent `N=2^14` configuration uses `p=5`; its preferred scrypt option is `N=2^17, r=8, p=1`.

Local benchmark:

```text
20 hashes:   approximately 0.36 seconds
20 verifies: approximately 0.35 seconds
```

Reference: [OWASP Password Storage Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html)

Resolution checklist:

- [ ] Prefer Argon2id or raise scrypt to a documented OWASP configuration.
- [ ] Benchmark the chosen cost on deployment hardware.
- [ ] Store algorithm parameters with each hash, as the current format already does.
- [ ] Support transparent rehashing after successful login when parameters change.

### RDB-011 — Authentication work can block and exhaust the API

**Severity:** P2  
**Type:** Availability and abuse-control gap  
**Status:** Open

Password hashing executes synchronously inside asynchronous request handlers. Registration and login have no rate limiting. A burst of requests can block the event loop and delay unrelated requests, including health checks.

Reference: [OWASP Denial of Service Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Denial_of_Service_Cheat_Sheet.html)

Resolution checklist:

- [ ] Run password hashing in a bounded worker thread.
- [ ] Add per-IP and per-account authentication rate limits.
- [ ] Add exponential cooldown or equivalent abuse controls.
- [ ] Ensure failure responses do not reveal whether an account exists.
- [ ] Load-test login while health and read endpoints remain responsive.

### RDB-012 — Cookie sessions have no explicit CSRF control

**Severity:** P2  
**Type:** Browser security gap  
**Status:** Open before browser UI deployment

Session cookies correctly use `HttpOnly`, production-only `Secure`, and `SameSite=Lax`. Tokens are opaque, random, and stored only as hashes. However, SameSite is defense in depth rather than a complete CSRF control for state-changing requests.

Reference: [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)

Resolution checklist:

- [ ] Add CSRF tokens or strict Origin/Referer verification for mutations.
- [ ] Decide whether production should use `SameSite=Strict`.
- [ ] Consider a `__Host-` cookie name in production.
- [ ] Add HSTS at the deployment edge.
- [ ] Test cross-origin mutation attempts.

### RDB-013 — Artifact checksum verification loads the entire file into memory

**Severity:** P2  
**Type:** Scalability and availability defect  
**Status:** Open

The download endpoint calls `path.read_bytes()` before returning `FileResponse`. Large CSV or Parquet artifacts are therefore read completely into API memory, and synchronous disk I/O blocks the event loop.

Relevant code:

- `src/research_data_builder/api/recipes.py`

Resolution checklist:

- [ ] Verify files incrementally in bounded chunks.
- [ ] Move verification and large-file serving off the API event loop.
- [ ] Avoid rehashing immutable object-storage artifacts on every download when storage integrity guarantees suffice.
- [ ] Add a large-artifact memory and latency test.

### RDB-014 — Provider discovery endpoints are documented but absent

**Severity:** P2  
**Type:** Product-completeness gap  
**Status:** Open

The system design documents provider and indicator search endpoints, but the OpenAPI document exposes no provider catalog routes. A future browser recipe editor cannot discover indicators, units, frequencies, or countries through the application API.

Relevant code and docs:

- `src/research_data_builder/main.py`
- `src/research_data_builder/providers/`
- `docs/SYSTEM_DESIGN.md`

Resolution checklist:

- [ ] Expose supported providers and capabilities.
- [ ] Add bounded indicator search.
- [ ] Add indicator metadata inspection.
- [ ] Add World Bank entity discovery.
- [ ] Apply authentication, caching, and rate limits.

### RDB-015 — API documentation and implementation disagree on comparison routing

**Severity:** P3  
**Type:** Documentation defect  
**Status:** Open

Documentation shows:

```text
GET /api/v1/builds/{build_id}/comparison?other_build_id={other_build_id}
```

Implementation exposes:

```text
GET /api/v1/builds/{build_id}/comparison/{other_build_id}
```

Relevant files:

- `src/research_data_builder/api/recipes.py`
- `docs/BUNDLES.md`
- `docs/SYSTEM_DESIGN.md`

Resolution checklist:

- [ ] Choose one stable route contract.
- [ ] Update OpenAPI tests and documentation together.

### RDB-016 — Partial artifact bundles can remain after export failure

**Severity:** P2  
**Type:** Artifact-publication defect  
**Status:** Open

Each file is replaced atomically, but the bundle directory is not published atomically as a unit. A failure after several writes can leave a partial failed bundle on disk. Re-execution may then mix cleanup and replacement behavior.

Relevant code:

- `src/research_data_builder/artifacts/exporter.py`

Resolution checklist:

- [ ] Write the full bundle into a unique temporary directory.
- [ ] Verify required files and checksums before publication.
- [ ] Atomically rename or promote the completed directory.
- [ ] Remove abandoned temporary bundles safely.
- [ ] Add injected-failure tests after each artifact write.

### RDB-017 — Expired sessions have no cleanup policy

**Severity:** P3  
**Type:** Operations gap  
**Status:** Open

Expired and revoked sessions stop authenticating correctly but remain in PostgreSQL indefinitely.

Resolution checklist:

- [ ] Add a bounded cleanup operation for expired and old revoked sessions.
- [ ] Define retention for security auditing.
- [ ] Add an index and batch deletion plan appropriate for the chosen retention window.

## Engineering openings

These findings create several strong opportunities to deepen the project and improve its value to employers.

### Opportunity A — Build a real authorization model

Ownership can demonstrate object-level authorization, safe not-found behavior, schema migration strategy, and multi-tenant isolation. The strongest evidence will be a two-user end-to-end test suite rather than only middleware.

### Opportunity B — Introduce an immutable build/attempt state machine

Separate logical build identity from execution attempts:

```text
logical build
└── attempt 1: failed
└── attempt 2: succeeded and immutable
└── refresh: new logical input identity and new build
```

This would solve overwrite, retry, crash recovery, cancellation, and audit-history concerns through one coherent model.

### Opportunity C — Turn recipes into a compiled research plan

Instead of interpreting separate pieces opportunistically, compile a recipe into validated ordered operations before retrieval. The compiler can reject ambiguous dimensionality, invalid date alignment, unsupported mixed-provider joins, and unsafe transformation sequences before expensive work begins.

### Opportunity D — Add adversarial and property-based correctness tests

Generate combinations across:

- frequency and partial-period boundaries;
- entity aliases;
- missing-value policies;
- transformation order;
- join types and dimensionality;
- one or many providers;
- empty, sparse, duplicated, and revised inputs.

These tests would be more meaningful for a research-data product than increasing line coverage alone.

### Opportunity E — Make asynchronous execution a reliability boundary

The Phase 7 queue should do more than move work out of HTTP requests. It should provide idempotency, leases, heartbeats, retry classification, stale-job recovery, cancellation, progress, and immutable attempt history.

### Opportunity F — Complete the researcher-facing discovery workflow

Provider catalog APIs and a small interface can turn raw indicator IDs into a usable product workflow:

```text
search indicator
→ inspect unit and frequency
→ select entities and dates
→ see required transformations
→ compile recipe
→ run and inspect build
```

### Opportunity G — Demonstrate secure hosted-app reasoning

Rate limiting, password-cost migration, CSRF protection, secure cookie configuration, object-level authorization, storage isolation, and audit events together provide a strong security and system-design story for recruiters.

## Recommended repair sequence

1. Resolve RDB-001 by adding ownership and authorization to every private route.
2. Resolve RDB-002, RDB-005, and RDB-009 with an immutable build/attempt state machine.
3. Resolve RDB-003, RDB-004, RDB-006, RDB-007, and RDB-008 through a compiled recipe execution plan.
4. Add adversarial regression tests for every confirmed reproduction.
5. Resolve RDB-010, RDB-011, and RDB-012 before exposing authentication publicly.
6. Resolve artifact publication and download findings before supporting large datasets.
7. Add provider discovery APIs before beginning the browser recipe editor.

## Definition of review closure

This review is considered closed only when:

- [ ] Every P0 and P1 item has a regression test and verified fix.
- [ ] Every private route has two-user isolation coverage.
- [ ] A successful build cannot be mutated or overwritten.
- [ ] The recipe engine either honors every declared option or rejects it explicitly.
- [ ] Concurrent and interrupted builds reach explainable states.
- [ ] Hosted authentication has documented rate limiting and CSRF controls.
- [ ] Documentation and OpenAPI describe the same product.
- [ ] GitHub Actions passes migration round trips and the full PostgreSQL suite.
