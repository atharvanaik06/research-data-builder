# Authentication and Browser Sessions

Phase 7 provides researcher accounts, revocable server-side sessions, and ownership enforcement for every private research resource.

## Account flow

```text
register or login
→ verify a memory-hard password hash
→ generate an opaque random token
→ store only its SHA-256 hash in PostgreSQL
→ return the raw token in an HTTP-only cookie
```

Passwords are hashed with `scrypt` using an independent 16-byte random salt. Login returns the same generic error for missing accounts, incorrect passwords, and inactive accounts.

The session cookie is:

- HTTP-only so browser JavaScript cannot read it;
- `SameSite=Lax` to limit cross-site cookie sending;
- marked `Secure` in production;
- bounded by the configured session lifetime;
- replaceable and individually revocable through its database record.

The raw session token is never stored. PostgreSQL contains only a SHA-256 lookup hash, expiry, revocation timestamp, and last-used timestamp.

## API

| Method and route | Purpose |
|---|---|
| `POST /api/v1/auth/register` | Create an account and begin a session. |
| `POST /api/v1/auth/login` | Verify credentials and begin a new session. |
| `POST /api/v1/auth/logout` | Revoke the current session and expire its cookie. |
| `GET /api/v1/auth/me` | Return the active account for the current session. |

Passwords must contain between 12 and 128 characters. Email addresses are trimmed and case-normalized before lookup and uniqueness enforcement.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `RESEARCH_DATA_SESSION_COOKIE_NAME` | `research_data_session` | Browser cookie name. |
| `RESEARCH_DATA_SESSION_TTL_HOURS` | `168` | Session lifetime, bounded to 1 hour–90 days. |

Migration `0005` creates `users` and `user_sessions`. Migration `0006` assigns an owner to every recipe and build. Repository methods flush but never commit; API services retain transaction ownership.

## Security boundary

The reusable `require_user` dependency resolves the current user from the hashed session record. Every recipe, version, build, validation, lineage, comparison, export, execution, and artifact-download route requires that user.

Repositories scope lookups by the current user's ID. A request for another user's resource receives the same `404` response as a request for an ID that does not exist, so the API does not reveal private resource existence. The OpenAPI document advertises the HTTP-only cookie security scheme on every private route.
