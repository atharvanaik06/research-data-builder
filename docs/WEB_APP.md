# Browser Workflow

## Purpose

The browser application makes the complete research workflow usable without direct API calls.

Open <http://localhost:8000/app> after the API and PostgreSQL start.

## Workflow

1. Create an account or sign in.
2. Name the dataset and select its date range, countries, and frequency.
3. Add one or more FRED or World Bank variables.
4. Select join, missing-value, and export rules.
5. Save and build the dataset.
6. Follow queued and running progress.
7. Inspect the preview and validation results.
8. Download the generated research files.

The interface also supports build cancellation, failed-build retry, forced provider refresh, and private activity history.

## Security boundary

The browser uses an HTTP-only session cookie. JavaScript cannot read this cookie. The API checks the session and resource owner for every private request.

The interface does not replace server checks. Recipe validation, ownership, limits, job state, and download authorization remain in the API and database layers.

## Current scope

The Phase 7 interface is a focused workflow, not a general dashboard. It supports the actions that a researcher needs to create and inspect a build. Phase 8 will deploy the same workflow to AWS.
