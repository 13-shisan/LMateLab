# LMateLab Production Correctness Design

## Context

The working tree contains a valid fix for a duplicate VASP `GET /api/db/vasp/cp_keys`
route, but production still runs an older image containing both route definitions. The
Celery Beat service also bind-mounts two host paths that Docker created as directories,
while the backend and worker use the real `var/db` directory.

## Goals

1. Make duplicate HTTP method/path registrations impossible to deploy silently.
2. Make backend liveness observable by Docker and the deployment procedure.
3. Give backend, worker, and beat the same database directory and database URLs.
4. Deploy the current backend fix with a preflight, consistent SQLite backups, health
   verification, and automatic backend image rollback.
5. Prevent `.env` and runtime data from entering future Python service images.

## Non-goals

- No database schema changes or migrations.
- No frontend or Nginx image rebuild.
- No cleanup of Git objects, build cache, lint debt, or large files.
- No ACS feed redesign; that is an independent upstream-availability problem.

## Route Integrity

`backend/route_integrity.py` will inspect the final FastAPI application, normalize each
route to `(HTTP method, full path)`, ignore `HEAD` and `OPTIONS`, and return every key
registered more than once. `assert_unique_routes(app)` will run after all routers are
included, so a duplicate prevents Gunicorn from starting instead of failing later on a
request. Unit tests will cover both a deliberately duplicated test app and the real
LMateLab app.

## Health Signal

`GET /api/health/live` will be a dependency-free liveness endpoint. It proves that the
application imported successfully, route validation passed, and a worker can answer an
HTTP request. Deployment verification calls it directly. Docker probes the new endpoint
first and falls back to the existing `/api/academic-reports` endpoint so the
previous image can still become healthy during an automatic rollback. Preflight exercises
the fallback against the live old image before any build or container change.

The password-policy loader will read `SECURITY_POLICY_PATH`, defaulting to the shared
`/app/var/data/security_policy.json` mount. This replaces the stale `/app/data` source path
that currently makes the registration policy endpoint return HTTP 500.
Database integrity remains covered by the existing migration containers and deployment
backup checks; liveness must not flap because an optional external service is slow.

## Database Mounts

Beat will replace the two invalid file bind mounts with the same
`./var/db:/app/var/db:rw` directory bind used by backend and worker. Its existing
`DATABASE_URL` and `DIGEST_DATABASE_URL` values then resolve to real SQLite files. A
host-side Compose integrity test will render the effective configuration and assert all
three services resolve `/app/var/db` from the same host source.

## Deployment And Rollback

`backend/.dockerignore` excludes environment files, databases, uploads, caches, and other
runtime state from `COPY . /app`. The deploy procedure rebuilds all three active Python
services so backend, worker, and beat no longer run images containing `/app/.env`.

`tools/deploy_backend_safely.sh` will:

1. Validate Compose and run the focused test suite.
2. Create consistent SQLite backups with the SQLite backup API.
3. Tag the currently running backend, worker, and beat images as timestamped rollback images.
4. Build and recreate backend, worker, and beat from the protected Docker context.
5. Wait for Docker health, verify one production `cp_keys` route, and require
   `https://matflow.top` to return HTTP 200.
6. Retag and restore all three previous service images automatically if deployment
   verification fails, then verify backend health and all three running states. A rollback
   that cannot be verified exits with a distinct critical error.

The frontend and Nginx containers are untouched.

## Verification

- Red/green unit tests for the route-integrity helper.
- Red/green Compose test for the shared database mount.
- Python syntax compilation for the backend.
- `docker compose config -q`.
- Clean backend test run.
- New backend container reports healthy.
- Production contains exactly one VASP `cp_keys` route.
- Active backend, worker, and beat containers contain no `/app/.env` file.
- `/api/auth/password-policy` returns HTTP 200 from the deployed image.
- `https://matflow.top` returns HTTP 200 after deployment.
- The public check validates the real TLS certificate; it does not disable verification.
