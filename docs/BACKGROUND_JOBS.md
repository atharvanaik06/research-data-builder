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
```

The job progress field uses these values:

```text
queued
retrieving
validating
exporting
succeeded
failed
```

## Ownership and duplicate requests

Each build attempt has at most one job. The queue locks the build row before it creates the job. Two requests cannot create two jobs for one build attempt.

Users can read only jobs that belong to their builds.

## Worker lease

The worker claims a job with a time-limited lease. The worker updates a heartbeat while it works.

If the lease expires, the system marks the job and build as failed. The error code is `worker_lease_expired`.

The system does not reuse the failed build record. The user creates a new numbered retry.

## Local services

Docker Compose starts these services:

```text
api
worker
postgres
```

The API and worker use the same application image. They use different process commands.
