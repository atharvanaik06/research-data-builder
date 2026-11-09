# Provider-Input Cache

## Purpose

Public data providers can be slow or temporarily unavailable. They can also limit request rates. The provider-input cache reduces repeated calls and keeps each build traceable.

## Default policy

The worker calculates a stable key from the provider, indicator, entities, and date range. It then looks for a cache entry that has not expired.

- A valid entry gives a cache hit.
- No valid entry gives a cache miss and a provider request.
- The refresh option bypasses valid entries and makes a provider request.
- The default lifetime is 24 hours.

Set `RESEARCH_DATA_PROVIDER_CACHE_TTL_HOURS` to change the lifetime.

## Reproducibility

Each cache entry is immutable. It stores:

- the normalized request.
- the normalized observations.
- a SHA-256 response fingerprint.
- the retrieval and expiry times.
- the observation count.
- the reuse count.

Each build input points to the exact entry that it used. It also records `hit`, `miss`, or `refresh`. A later refresh cannot change an older build input.

## Researcher control

The browser includes a **Request fresh provider data** option. The build API also accepts `refresh_provider_inputs=true` when it queues a build.

Use a forced refresh when recent provider changes are important. Use the default cache policy for normal development and repeated builds.
