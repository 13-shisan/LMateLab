# LMateLab Production Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent duplicate FastAPI routes, correct Beat's database mounts, and deploy the backend safely with health verification and rollback.

**Architecture:** Validate the final FastAPI route table at import time, expose a dependency-free liveness endpoint, and render Compose configuration in a host-side integrity test. A deployment script backs up SQLite, preserves the old image, deploys only backend and Beat, and restores the old backend image if health checks fail.

**Tech Stack:** Python 3.12, FastAPI, unittest, Docker Compose v5, Bash, SQLite.

---

### Task 1: Route Integrity Guard

**Files:**
- Create: `backend/route_integrity.py`
- Modify: `backend/tests/test_route_integrity.py`

- [ ] **Step 1: Write failing helper tests**

Add tests that build a small FastAPI app with two `GET /duplicate` routes and expect
`duplicate_routes()` to report them and `assert_unique_routes()` to raise `RuntimeError`.

- [ ] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=backend python -m unittest backend.tests.test_route_integrity -v
```

Expected: import failure because `route_integrity` does not exist.

- [ ] **Step 3: Implement the minimal guard**

```python
from collections import defaultdict


IGNORED_METHODS = {"HEAD", "OPTIONS"}


def duplicate_routes(app):
    registrations = defaultdict(list)
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if not path:
            continue
        for method in methods:
            method = method.upper()
            if method not in IGNORED_METHODS:
                registrations[(method, path)].append(getattr(route, "name", "<unnamed>"))
    return {key: names for key, names in registrations.items() if len(names) > 1}


def assert_unique_routes(app):
    duplicates = duplicate_routes(app)
    if duplicates:
        details = "; ".join(
            f"{method} {path}: {', '.join(names)}"
            for (method, path), names in sorted(duplicates.items())
        )
        raise RuntimeError(f"duplicate FastAPI routes: {details}")
```

- [ ] **Step 4: Verify GREEN**

Run the focused unittest command and expect all helper tests to pass.

### Task 2: Application Guard And Health

**Files:**
- Create: `backend/routers/health.py`
- Modify: `backend/main.py`
- Modify: `backend/tests/test_route_integrity.py`

- [ ] **Step 1: Write a failing real-application test**

Add a test that imports `main.app` and expects `duplicate_routes(app) == {}`. Add a test
that locates `/api/health/live` and calls its endpoint, expecting `{"status": "ok"}`.

- [ ] **Step 2: Verify RED**

Run the focused tests and expect the health-route assertion to fail because the endpoint
does not exist.

- [ ] **Step 3: Add the health router and startup assertion**

```python
# backend/routers/health.py
from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", include_in_schema=False)
def live():
    return {"status": "ok"}
```

Include this router in `api_router`, then call `assert_unique_routes(app)` immediately
after `app.include_router(api_router)`.

- [ ] **Step 4: Verify GREEN**

Run the focused tests and expect the real application route table and health endpoint to
pass.

### Task 3: Shared Database Mount And Healthcheck

**Files:**
- Create: `backend/tests/test_compose_integrity.py`
- Modify: `docker-compose.prod.yml`

- [ ] **Step 1: Write the failing Compose test**

Render `docker compose config --format json`, find each service's bind mount targeting
`/app/var/db`, and assert backend, worker, and beat all resolve the same existing host
directory.

- [ ] **Step 2: Verify RED**

Run:

```bash
python -m unittest backend.tests.test_compose_integrity -v
```

Expected: Beat has no `/app/var/db` directory mount.

- [ ] **Step 3: Correct Compose**

Replace Beat's two file mounts with:

```yaml
- ./var/db:/app/var/db:rw
```

Add this backend healthcheck:

```yaml
healthcheck:
  test:
    - CMD-SHELL
    - >-
      python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4000/api/health/live', timeout=5)"
      || python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4000/api/academic-reports?page=1&page_size=1', timeout=5)"
  interval: 10s
  timeout: 6s
  retries: 12
  start_period: 30s
```

- [ ] **Step 4: Verify GREEN**

Run the Compose test and `docker compose -f docker-compose.prod.yml config -q`.

### Task 4: Safe Deployment Script

**Files:**
- Create: `backend/.dockerignore`
- Create: `backend/tests/test_docker_context_integrity.py`
- Create: `backend/tests/test_security_policy.py`
- Modify: `backend/schemas.py`
- Create: `tools/deploy_backend_safely.sh`

- [ ] **Step 1: Implement preflight and backup**

First add a failing test requiring `.dockerignore` to exclude `.env`, `.env.*`, Python
caches, databases, uploads, custom databases, and runtime data. Add the minimal ignore
file and verify the test turns green.

The script must use `set -Eeuo pipefail`, render Compose, run backend tests, and use
Python's SQLite backup API to copy `eln.db` and `digests.db` into a timestamped
`var/backups/` directory.

- [ ] **Step 2: Implement deployment and rollback**

Capture the current backend, worker, and beat image IDs, tag them with a timestamp, build
and recreate all three services, and install an `ERR` trap that restores all three old
images and containers.

- [ ] **Step 3: Implement post-deploy verification**

Wait until `.State.Health.Status` is `healthy`, assert the production container has one
`GET /api/db/vasp/cp_keys` registration, assert Beat sees both database paths as files,
assert no active Python service image contains `/app/.env`, and require
the new `/api/health/live` endpoint and a certificate-validating
`curl https://matflow.top` request to succeed. The rollback path must restore all three
images, verify the backend's compatibility healthcheck, and confirm every service is
running; otherwise it exits with a distinct critical status.

Add a focused policy-loader test using a temporary `SECURITY_POLICY_PATH`, change the
runtime default to `/app/var/data/security_policy.json`, and verify the deployed
`/api/auth/password-policy` endpoint returns HTTP 200.

- [ ] **Step 4: Syntax-check the script**

Run `bash -n tools/deploy_backend_safely.sh` and expect exit 0.

### Task 5: Full Verification And Production Deployment

**Files:**
- Verify all modified files.

- [ ] **Step 1: Run static and unit verification**

```bash
PYTHONPATH=backend python -m unittest discover -s backend/tests -v
find backend -name '*.py' -not -path '*/__pycache__/*' -print0 | xargs -0 -n1 python -m py_compile
docker compose -f docker-compose.prod.yml config -q
git diff --check
```

- [ ] **Step 2: Execute deployment**

```bash
bash tools/deploy_backend_safely.sh
```

- [ ] **Step 3: Read back production state**

Confirm backend is healthy, Beat database mounts point at `var/db`, exactly one VASP
`cp_keys` route is registered, and `https://matflow.top` returns HTTP 200.

- [ ] **Step 4: Commit the scoped fix**

Stage only the backend correctness files, Compose change, tests, script, design, and plan.
Do not stage the user's frontend, CSS, or Nginx changes.
