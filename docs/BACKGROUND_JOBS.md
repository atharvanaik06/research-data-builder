# Background Build Jobs

The API does not execute a dataset build inside the web request. It creates a durable PostgreSQL job and returns `202 Accepted`.

```text
POST build execution request
→ create one queued job
→ return the job immediately
→ worker claims the job
→ worker builds the dataset
→ worker stores the final status
```

## Job states

```text
queued → running → succeeded
                 → failed
                 → cancelled

queued → cancelled
```

The job progress field uses these values:

```text
queued
retrieving
validating
exporting
finalizing
cancelling
succeeded
failed
cancelled
```

## Ownership and duplicate requests

Each build attempt has at most one job. The queue locks the build row before it creates the job. Two requests cannot create two jobs for one build attempt.

Users can read only jobs that belong to their builds.

## Worker lease

The worker claims a job with a time-limited lease. The worker updates a heartbeat while it works.

If the lease expires, the system marks the job and build as failed. The error code is `worker_lease_expired`.

The system does not reuse the failed build record. The user creates a new numbered retry.

## Automatic retries

The worker retries temporary provider failures. These failures include network errors, rate limits, and provider server errors.

Each retry creates a new numbered build and a new job. The worker keeps the failed build as history.

The worker waits 5 seconds before attempt 2. It waits 10 seconds before attempt 3. The worker stops after attempt 3.

The worker does not retry configuration errors, invalid provider responses, validation failures, or export failures.

## Cancellation

The user can cancel a queued or running build with this route:

```text
POST /api/v1/builds/{build_id}/cancel
```

The system cancels a queued job immediately.

For a running job, the system records a cancellation request. The worker checks for this request while it runs. It stops the active operation and marks the job and build as `cancelled`.

Cancellation is idempotent. A second cancellation request returns the same cancelled job. A successful or failed job cannot become cancelled.

The system keeps the cancelled build record. It stores the error code `cancelled_by_user` so the audit history shows why the build stopped.

The user can retry a cancelled build. The retry creates a new numbered build and keeps the cancelled build as history.

## Local services

Docker Compose starts these services:

```text
api
worker
postgres
```

The API and worker use the same application image. They use different process commands.
