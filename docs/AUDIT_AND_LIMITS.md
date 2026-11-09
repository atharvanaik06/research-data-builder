# Audit History and User Limits

## Private activity history

The system records important account activity in PostgreSQL. A signed-in user can view only their own events at `GET /api/v1/audit-events`.

Recorded actions include:

- recipe creation and updates.
- recipe version creation.
- build planning and queueing.
- cancellation and retry requests.
- worker success, failure, retry, and cancellation.
- artifact downloads.

Each event contains the actor, action, resource type, resource ID, safe details, and time. Events must not store passwords, session tokens, provider keys, or dataset contents.

## User limits

Two limits protect the shared service from one account that submits too much work.

| Setting | Default | Behavior |
|---|---:|---|
| `RESEARCH_DATA_MAX_RECIPE_BYTES` | 65,536 bytes | Reject a recipe that is too large. |
| `RESEARCH_DATA_MAX_OUTSTANDING_BUILDS_PER_USER` | 5 | Reject a new job when the user already has the maximum queued and running jobs. |

The job limit returns HTTP `429` with the stable error code `user_build_limit`. Finished, failed, and cancelled jobs do not count as outstanding work.

## Why these controls matter

The audit history helps a researcher explain what happened. The limits keep the system available when several users work at the same time. Phase 8 will add infrastructure limits, alarms, and cost controls.
