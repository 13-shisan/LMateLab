# Server Monitor Resource Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild MatFlow server monitoring around physical servers, visible login accounts, strict lab-member filtering, accurate global resource occupancy, and reliable automatic or assisted snapshot collection.

**Architecture:** Add a validated catalog and member registry, normalize legacy and version-2 snapshots into separate physical-resource and lab-usage scopes, and expose new compatibility-safe APIs while retaining current routes. Reachable sources continue through a catalog-driven node21 collector; isolated sources use an interactive Windows relay or authenticated browser upload. React pages consume the new APIs through focused model helpers and a responsive CSS-based operations layout.

**Tech Stack:** FastAPI, Pydantic 2, Python 3.12, JSON file storage, `fcntl`/atomic writes, React 19, Vite 7, Axios, Lucide React, Node test runner, PowerShell 7/OpenSSH, Docker Compose, Nginx, Playwright CLI.

---

## File Responsibility Map

### Backend configuration and domain services

- Create `backend/config/server_monitor_catalog.json`: physical servers, accounts, legacy sources, transports, freshness thresholds, and snapshot priority.
- Create `backend/config/server_monitor_members.json`: canonical member IDs, verified display names, and case-insensitive aliases.
- Create `backend/services/server_monitor/__init__.py`: package boundary.
- Create `backend/services/server_monitor/catalog.py`: Pydantic models, JSON loading, validation, digest, and legacy lookup.
- Create `backend/services/server_monitor/scopes.py`: user classification and global/lab metric separation.
- Create `backend/services/server_monitor/snapshots.py`: legacy/version-2 readers, resource-truth selection, health, conflict detection, and history bucketing.
- Create `backend/services/server_monitor/overview.py`: physical-server list/detail and lab-member overview aggregation.
- Create `backend/services/server_monitor/ingest.py`: token verification, upload validation, sanitization, locking, and atomic persistence.
- Create `backend/routers/server_monitor_ingest.py`: relay-token ingestion route without JWT dependency.
- Modify `backend/routers/server_monitor.py`: add authenticated version-2 read/upload endpoints while preserving legacy endpoints.
- Modify `backend/main.py`: register ingestion router.
- Modify `docker-compose.prod.yml`: mount a narrow writable ingestion directory and configure catalog/token paths.

### Collection and operational tools

- Modify `tools/server_monitor/collect_server_status.py`: CLI arguments, versioned envelope, stdout mode, and reusable atomic writer.
- Create `tools/server_monitor/sync_sources.py`: catalog-driven local/rsync synchronization, per-source status, timeouts, and locks.
- Modify `var/artifacts/server_monitor/sync_all.sh` on production only after dry-run validation: compatibility wrapper invoking `sync_sources.py`.
- Create `tools/server_monitor/server-monitor-sync.logrotate`: bounded source logs.
- Create `tools/server_monitor/install_remote_collector.sh`: backup/install/cron helper for reachable accounts.
- Create `tools/server_monitor/windows/Sync-ServerMonitorSnapshot.ps1`: interactive SSH/MFA relay and HTTPS upload.
- Create `tools/server_monitor/windows/README.md`: Windows preflight, credential storage, update, and recovery instructions.

### Frontend

- Create `frontend/src/pages/server_monitor/serverMonitorApi.js`: API calls and upload form construction.
- Create `frontend/src/pages/server_monitor/serverMonitorModel.js`: stable sorting, formatting, grouped filters, and responsive view-model helpers.
- Create `frontend/src/pages/server_monitor/ServerMonitor.css`: operations-board, worktable, account, state, typography, and responsive styles.
- Create `frontend/src/pages/server_monitor/ServerHealthBadge.jsx`: consistent status presentation.
- Create `frontend/src/pages/server_monitor/ServerAccountList.jsx`: expandable account status without duplicated resource metrics.
- Modify `frontend/src/pages/server_monitor/ServerMonitorLayout.jsx`: remove hardcoded server list and use physical-server catalog options.
- Modify `frontend/src/pages/server_monitor/ServerMonitorEntry.jsx`: compact physical-server operations board.
- Modify `frontend/src/pages/server_monitor/ServerMonitorUsersOverview.jsx`: allowlisted member worktable and coverage/trend tabs.
- Modify `frontend/src/pages/server_monitor/ServerMonitorPage.jsx`: physical-server detail with global/lab scopes and account metadata.

### Tests and deployment

- Create `backend/requirements-server-monitor-test.txt`.
- Create `tools/test_server_monitor_backend.sh`.
- Create `backend/tests/test_server_monitor_catalog.py`.
- Create `backend/tests/test_server_monitor_scopes.py`.
- Create `backend/tests/test_server_monitor_snapshots.py`.
- Create `backend/tests/test_server_monitor_api.py`.
- Create `backend/tests/test_server_monitor_ingest.py`.
- Create `backend/tests/test_server_monitor_tools.py`.
- Modify `backend/tests/test_server_monitor_history.py`.
- Create `frontend/tests/serverMonitorModel.test.mjs`.
- Create `frontend/tests/serverMonitorPresentation.test.mjs`.
- Modify `backend/tests/test_compose_integrity.py`.
- Modify `backend/tests/test_deploy_script_integrity.py`.
- Modify `tools/deploy_backend_safely.sh`.
- Create `tools/deploy_frontend_safely.sh`.

## Catalog Records Required in Task 1

| Physical ID | Display | Account ID | Source | Mode | Transport |
| --- | --- | --- | --- | --- | --- |
| `dell` | Dell服务器 | `Pwjb` | `Dell` | `node21_pull` | `local` |
| `dell-gpu` | 4090服务器 | `Pwjb` | `Dell-GPU` | `node21_pull` | `local` |
| `dawn4` | Dawn4 | `Pwjb` | `Dawn4` | `node21_pull` | `rsync` |
| `dawn5` | Dawn5 | `Pwjb` | `Dawn5` | `node21_pull` | `rsync` |
| `sugon` | 曙光服务器 | `Pwjb` | `Sugon` | `node21_pull` | `rsync` |
| `jingzhun` | 精准平台 | `xjwu` | `Jingzhun-xjwu` | `node21_pull` | `rsync` |
| `jingzhun` | 精准平台 | `jbwu` | `Jingzhun-jbwu` | `node21_pull` | `rsync` |
| `jingzhun-gpu` | 精准平台 GPU | `jingzhun-gpu-account` | `Jingzhun-GPU` | `windows_relay` | `ssh` |
| `shuangyiliu-huayuan` | 双一流化院 | `xjwu` | `Shuangyiliu-huayuan` | `node21_pull` | `rsync` |
| `shuangyiliu-hfnl` | 双一流微尺度 | `xjwu` | `Shuangyiliu-HFNL-xjwu` | `node21_pull` | `rsync` |
| `shuangyiliu-hfnl` | 双一流微尺度 | `hflv` | `Shuangyiliu-HFNL-hflv` | `node21_pull` | `rsync` |
| `shuangyiliu-hfnl` | 双一流微尺度 | `wjb` | `Shuangyiliu-HFNL-wjb` | `node21_pull` | `rsync` |
| `scnet` | 合肥超算 | `scnet-account` | `SCNet` | `windows_relay` | `ssh` |
| `wuxi` | 无锡超算 | `wuxi-account` | `Wuxi` | `windows_relay` | `ssh` |
| `dongfang` | 东方超算 | `xjwu` | `Dongfang-xjwu` | `windows_relay` | `ssh` |
| `dongfang` | 东方超算 | `yang4` | `Dongfang-yang4` | `windows_relay` | `ssh` |

The three source-specific IDs ending in `-account` use `setup_state: "account_unconfirmed"`. They are stable internal keys, not inferred login names; the UI renders “账号待确认” until the catalog is explicitly updated.

### Task 0: Establish the Isolated Execution and Test Harness

**Files:**
- Create: `backend/requirements-server-monitor-test.txt`
- Create: `tools/test_server_monitor_backend.sh`

- [ ] **Step 1: Add a minimal pinned backend test environment**

```text
fastapi==0.115.0
httpx==0.27.2
pydantic==2.8.2
email-validator==2.3.0
PyJWT==2.9.0
SQLAlchemy==2.0.31
python-dotenv==1.2.1
passlib==1.7.4
bcrypt==4.0.1
python-multipart==0.0.9
pytest==8.3.5
```

This file intentionally excludes scientific, ML, MinerU, and Celery packages that the server-monitor unit/API tests do not import.

- [ ] **Step 2: Add the reusable Docker test runner**

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

if (( $# == 0 )); then
  printf 'usage: %s <pytest-selector> [pytest-args...]\n' "${0##*/}" >&2
  exit 2
fi

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v cygpath >/dev/null 2>&1; then
  ROOT="$(cygpath -w "$ROOT")"
  export MSYS_NO_PATHCONV=1
fi

docker run --rm \
  -e JWT_SECRET=test-only-server-monitor-secret \
  -e LMATELAB_DATA_DIR=/tmp/lmatelab-test-var \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -v lmatelab_server_monitor_test_pip:/root/.cache/pip \
  -v "$ROOT/backend:/app:ro" \
  -w /app \
  python:3.12-slim-bookworm \
  sh -lc 'pip install -q -r requirements-server-monitor-test.txt && exec python -m pytest -q -p no:cacheprovider "$@"' sh "$@"
```

- [ ] **Step 3: Verify the baseline server-monitor application tests locally**

Run:

```bash
bash tools/test_server_monitor_backend.sh \
  tests/test_server_monitor_history.py
```

Expected: zero failures. Pass only explicit application/unit test selectors to this minimal runner; run host-dependent Compose and deployment integrity tests in Step 8.

- [ ] **Step 4: Verify the baseline frontend tests and build**

Run in `frontend`: `npm test && npm run build`.

Expected: all Node tests pass and Vite exits 0.

- [ ] **Step 5: Commit the test harness**

```bash
git add backend/requirements-server-monitor-test.txt tools/test_server_monitor_backend.sh
git commit -m "test: add server monitor test harness"
```

- [ ] **Step 6: Publish the feature branch to the production repository without changing production master**

Run from the Windows worktree:

```powershell
git push -u origin codex/server-monitor-resource-model
```

Expected: a new branch is created in `/home/software/LMateLab`; production `master` remains checked out.

- [ ] **Step 7: Create a remote linked worktree for final Linux/container tests**

```powershell
ssh Pwjb@222.195.94.37 "cd /home/software/LMateLab && git worktree add .worktrees/server-monitor-resource-model codex/server-monitor-resource-model"
```

Expected: `/home/software/LMateLab/.worktrees/server-monitor-resource-model` exists and is not the production checkout.

- [ ] **Step 8: Verify host-dependent integrity tests with node21 host Python**

Run from the remote linked worktree. The ignored empty `.env` exists only so Docker Compose can render the configuration and is removed when the shell exits.

```bash
cd /home/software/LMateLab/.worktrees/server-monitor-resource-model
(
  test ! -e backend/.env
  touch backend/.env
  trap 'rm -f backend/.env' EXIT
  python3 -m pytest -q \
    backend/tests/test_compose_integrity.py \
    backend/tests/test_deploy_script_integrity.py \
    backend/tests/test_docker_context_integrity.py \
    backend/tests/test_runtime_recovery_integrity.py
)
```

Expected: zero failures.

- [ ] **Step 9: Verify application tests in a disposable production-image container**

```bash
docker run --rm \
  -e JWT_SECRET=test-only-server-monitor-secret \
  -e LMATELAB_DATA_DIR=/tmp/lmatelab-test-var \
  -e DATABASE_URL=sqlite:////tmp/lmatelab-test-eln.db \
  -e DIGEST_DATABASE_URL=sqlite:////tmp/lmatelab-test-digests.db \
  -v /home/software/LMateLab/.worktrees/server-monitor-resource-model/backend:/app \
  -w /app lmatelab-backend \
  sh -lc 'pip install -q pytest && exec python -m pytest -q tests \
    --ignore=tests/test_compose_integrity.py \
    --ignore=tests/test_deploy_script_integrity.py \
    --ignore=tests/test_docker_context_integrity.py \
    --ignore=tests/test_runtime_recovery_integrity.py'
```

Expected: zero failures. Do not continue if the baseline fails without first identifying the cause.

### Task 1: Add the Validated Physical-Server Catalog and Member Registry

**Files:**
- Create: `backend/config/server_monitor_catalog.json`
- Create: `backend/config/server_monitor_members.json`
- Create: `backend/services/server_monitor/__init__.py`
- Create: `backend/services/server_monitor/catalog.py`
- Create: `backend/tests/test_server_monitor_catalog.py`

- [ ] **Step 1: Write catalog tests that fail before the loader exists**

```python
def test_confirmed_multi_account_groups(catalog):
    assert [a.id for a in catalog.physical("shuangyiliu-hfnl").accounts] == ["xjwu", "hflv", "wjb"]
    assert [a.id for a in catalog.physical("dongfang").accounts] == ["xjwu", "yang4"]
    assert [a.id for a in catalog.physical("jingzhun").accounts] == ["xjwu", "jbwu"]
    assert catalog.physical("jingzhun-gpu").id != catalog.physical("jingzhun").id

def test_external_examples_are_not_members(registry):
    for username in ("zhangwh", "whzhang", "qxli", "bli", "bcpan"):
        assert registry.resolve(username) is None
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `bash tools/test_server_monitor_backend.sh tests/test_server_monitor_catalog.py`

Expected: collection fails because `services.server_monitor.catalog` does not exist.

- [ ] **Step 3: Implement typed loaders and immutable lookups**

```python
class AccountConfig(BaseModel):
    id: str
    display_name: str
    source_id: str
    legacy_source: str | None = None
    login: str | None = None
    host: str | None = None
    mode: Literal["node21_pull", "windows_relay", "manual_upload"]
    transport: Literal["local", "rsync", "ssh", "upload"]
    expected_interval_minutes: int = Field(gt=0)
    stale_after_minutes: int = Field(gt=0)
    snapshot_priority: int = 100
    setup_state: Literal["configured", "pending_setup", "account_unconfirmed"] = "configured"

class PhysicalServerConfig(BaseModel):
    id: str
    display_name: str
    scheduler: Literal["pbs", "slurm", "unknown"]
    accounts: list[AccountConfig] = Field(min_length=1)

class ServerMonitorCatalog(BaseModel):
    schema_version: Literal[1]
    physical_servers: list[PhysicalServerConfig]

    def physical(self, physical_id: str) -> PhysicalServerConfig:
        match = next((item for item in self.physical_servers if item.id == physical_id), None)
        if match is None:
            raise KeyError(physical_id)
        return match

class MemberConfig(BaseModel):
    id: str
    display_name: str
    aliases: list[str] = Field(min_length=1)

class MemberRegistry:
    def __init__(self, members: list[MemberConfig]):
        self.members = tuple(members)
        self._by_alias = {
            alias.strip().lower(): member
            for member in members
            for alias in member.aliases
            if alias.strip()
        }

    def resolve(self, username: str) -> MemberConfig | None:
        return self._by_alias.get(str(username or "").strip().lower())
```

Load both JSON files from environment-overridable paths, reject duplicate physical/account/source IDs, and expose `catalog_digest()` and `member_registry_digest()` using canonical sorted JSON.

- [ ] **Step 4: Populate the catalog and all 28 canonical member IDs**

Use the exact catalog table in this plan. Populate member IDs from the design specification, migrate existing valid aliases case-insensitively, and omit all five confirmed external examples.

- [ ] **Step 5: Run tests and commit**

Run: `bash tools/test_server_monitor_backend.sh tests/test_server_monitor_catalog.py`

Expected: PASS.

```bash
git add backend/config backend/services/server_monitor backend/tests/test_server_monitor_catalog.py
git commit -m "feat: add server monitor catalog"
```

### Task 2: Separate Global Resource Truth from Lab-Member Usage

**Files:**
- Create: `backend/services/server_monitor/scopes.py`
- Create: `backend/tests/test_server_monitor_scopes.py`

- [ ] **Step 1: Write the external-load invariant test**

```python
def test_external_jobs_do_not_turn_busy_nodes_into_free_nodes(member_registry):
    snapshot = {
        "overview": {"node_total": 5, "node_busy": 2, "node_free": 3, "node_down": 0},
        "scheduler": {"jobs": [
            {"job_id": "1", "user": "zhangwh", "state": "RUNNING", "node": "n01"},
            {"job_id": "2", "user": "qxli", "state": "RUNNING", "node": "n02"},
        ]},
    }
    result = build_scoped_snapshot(snapshot, member_registry)
    assert result.resource_summary["node_busy"] == 2
    assert result.resource_summary["node_free"] == 3
    assert result.resource_summary["total_running_jobs"] == 2
    assert result.lab_summary["running_jobs"] == 0
    assert result.lab_jobs == []
```

- [ ] **Step 2: Run the test and verify RED**

Run: `bash tools/test_server_monitor_backend.sh tests/test_server_monitor_scopes.py`

Expected: FAIL because `build_scoped_snapshot` is missing.

- [ ] **Step 3: Implement classification without mutating resource fields**

```python
class ScopedSnapshot(BaseModel):
    resource_summary: dict
    lab_summary: dict
    external_load: dict
    lab_jobs: list[dict]

    @classmethod
    def from_values(
        cls,
        overview: dict,
        total_running: int,
        total_queued: int,
        external_running: int,
        external_queued: int,
        lab_jobs: list[dict],
    ) -> "ScopedSnapshot":
        lab_running = sum(str(job.get("state") or "").upper() in {"R", "RUNNING"} for job in lab_jobs)
        lab_queued = sum(str(job.get("state") or "").upper() in {"Q", "PENDING"} for job in lab_jobs)
        resource_summary = dict(overview)
        resource_summary.update({"total_running_jobs": total_running, "total_queued_jobs": total_queued})
        return cls(
            resource_summary=resource_summary,
            lab_summary={"running_jobs": lab_running, "queued_jobs": lab_queued},
            external_load={"running_jobs": external_running, "queued_jobs": external_queued},
            lab_jobs=lab_jobs,
        )

def build_scoped_snapshot(payload: dict, members: MemberRegistry) -> ScopedSnapshot:
    scheduler = payload.get("scheduler") or {}
    jobs = list(scheduler.get("jobs") or [])
    lab_jobs: list[dict] = []
    external_running = 0
    external_queued = 0
    total_running = 0
    total_queued = 0
    for job in jobs:
        state = str(job.get("state") or "").upper()
        is_running = state in {"R", "RUNNING"}
        is_queued = state in {"Q", "PENDING"}
        total_running += int(is_running)
        total_queued += int(is_queued)
        member = members.resolve(str(job.get("user") or ""))
        if member is None:
            external_running += int(is_running)
            external_queued += int(is_queued)
            continue
        lab_jobs.append({**job, "user": member.id, "display_name": member.display_name})
    overview = payload.get("overview") or {}
    return ScopedSnapshot.from_values(
        overview=overview,
        total_running=total_running,
        total_queued=total_queued,
        external_running=external_running,
        external_queued=external_queued,
        lab_jobs=lab_jobs,
    )
```

`ScopedSnapshot.from_values` copies `node_total`, `node_busy`, `node_free`, `node_down`, CPU, memory, disk, and GPU values directly from the full snapshot. It never derives free capacity from lab jobs.

- [ ] **Step 4: Add privacy tests and commit**

Assert serialized output contains no external username, job name, work directory, or command field, while anonymous external running/queued counts remain.

Run: `bash tools/test_server_monitor_backend.sh tests/test_server_monitor_scopes.py`

```bash
git add backend/services/server_monitor/scopes.py backend/tests/test_server_monitor_scopes.py
git commit -m "feat: separate server resource and lab usage scopes"
```

### Task 3: Select One Resource-Truth Snapshot per Physical Server

**Files:**
- Create: `backend/services/server_monitor/snapshots.py`
- Create: `backend/tests/test_server_monitor_snapshots.py`
- Modify: `backend/tests/test_server_monitor_history.py`

- [ ] **Step 1: Write failing three-account deduplication tests**

Create three `shuangyiliu-hfnl` snapshots with identical node/job state and different account IDs. Assert `select_resource_truth()` returns one candidate, three account statuses, and one copy of each job. Create a second fixture where node totals differ and assert health is `inconsistent`.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `bash tools/test_server_monitor_backend.sh tests/test_server_monitor_snapshots.py tests/test_server_monitor_history.py`

Expected: FAIL because the repository and physical history iterator are missing.

- [ ] **Step 3: Implement deterministic selection**

```python
@dataclass(frozen=True)
class SnapshotCandidate:
    account_id: str
    collected_at: datetime
    snapshot_priority: int
    resource_fingerprint: str
    stale_after_minutes: int
    validation_error: str | None
    payload: dict

    def is_fresh(self, now: datetime) -> bool:
        return now - self.collected_at <= timedelta(minutes=self.stale_after_minutes)

    def health(self, now: datetime) -> str:
        return "normal" if self.is_fresh(now) else "stale"

    def account_status(self, now: datetime) -> dict:
        return {"account_id": self.account_id, "collected_at": self.collected_at.isoformat(), "health": self.health(now)}

@dataclass(frozen=True)
class PhysicalSnapshot:
    selected: SnapshotCandidate
    account_statuses: list[dict]
    health: str

class SnapshotUnavailable(RuntimeError):
    pass

def select_resource_truth(candidates: list[SnapshotCandidate], now: datetime) -> PhysicalSnapshot:
    valid = [item for item in candidates if item.validation_error is None and item.collected_at <= now + timedelta(minutes=10)]
    if not valid:
        raise SnapshotUnavailable("no valid snapshot")
    valid.sort(key=lambda item: (item.collected_at, -item.snapshot_priority), reverse=True)
    selected = valid[0]
    fingerprints = {item.resource_fingerprint for item in valid if item.is_fresh(now)}
    health = "inconsistent" if len(fingerprints) > 1 else selected.health(now)
    return PhysicalSnapshot(selected=selected, account_statuses=[item.account_status(now) for item in candidates], health=health)
```

Use resource fingerprints based on hostname, scheduler type, node totals/states, and sorted scheduler job IDs/states. Do not union sibling account jobs.

- [ ] **Step 4: Implement legacy adapters and date-pruned physical history**

Resolve legacy directories through the catalog, retain the existing date-directory pruning, select one account snapshot per physical server/time bucket, and key historical jobs by `(physical_server_id, job_id)`.

- [ ] **Step 5: Run tests and commit**

Run: `bash tools/test_server_monitor_backend.sh tests/test_server_monitor_snapshots.py tests/test_server_monitor_history.py`

```bash
git add backend/services/server_monitor/snapshots.py backend/tests/test_server_monitor_snapshots.py backend/tests/test_server_monitor_history.py
git commit -m "feat: deduplicate physical server snapshots"
```

### Task 4: Add Compatibility-Safe Physical Server APIs and Overview Cache

**Files:**
- Create: `backend/services/server_monitor/overview.py`
- Modify: `backend/routers/server_monitor.py`
- Modify: `backend/tests/test_server_monitor_history.py`
- Create: `backend/tests/test_server_monitor_api.py`

- [ ] **Step 1: Write failing API contract tests**

Test these authenticated endpoints:

```text
GET /api/server-monitor/physical-servers
GET /api/server-monitor/physical/{physical_server_id}
GET /api/server-monitor/physical/{physical_server_id}/usage?range=30d
GET /api/server-monitor/users-overview-v2?range=30d
```

Assert physical responses contain `resource_summary`, `lab_summary`, and nested `accounts`; overview users are canonical allowlisted members only; legacy `/servers`, `/status/{legacy_source}`, `/usage/{legacy_source}`, and `/users-overview` remain callable.

- [ ] **Step 2: Run tests and verify RED**

Run: `bash tools/test_server_monitor_backend.sh tests/test_server_monitor_api.py tests/test_server_monitor_history.py`

- [ ] **Step 3: Implement overview service and router adapters**

```python
@router.get("/physical-servers")
def get_physical_servers():
    return overview_service.list_physical_servers()

@router.get("/physical/{physical_server_id}")
def get_physical_server(physical_server_id: str):
    return overview_service.get_physical_server(physical_server_id)

@router.get("/users-overview-v2")
def get_users_overview_v2(background_tasks: BackgroundTasks, range: str = Query("30d")):
    days = parse_range_to_days(range)
    return overview_service.get_users_overview(days, background_tasks.add_task)
```

Cache filenames include range plus catalog/member digests, for example `users-overview-v2-30d-<digest>.json`. Stale caches return immediately and refresh under the existing `flock` pattern.

- [ ] **Step 4: Run complete server-monitor backend tests and commit**

Run: `bash tools/test_server_monitor_backend.sh tests/test_server_monitor_*.py`

```bash
git add backend/services/server_monitor/overview.py backend/routers/server_monitor.py backend/tests
git commit -m "feat: expose physical server monitor APIs"
```

### Task 5: Add Secure Snapshot Ingestion and Browser Upload

**Files:**
- Create: `backend/services/server_monitor/ingest.py`
- Create: `backend/routers/server_monitor_ingest.py`
- Create: `backend/tests/test_server_monitor_ingest.py`
- Modify: `backend/routers/server_monitor.py`
- Modify: `backend/main.py`
- Modify: `docker-compose.prod.yml`
- Modify: `backend/tests/test_compose_integrity.py`

- [ ] **Step 1: Write failing security tests**

Cover valid scoped token, wrong-source token, missing token, path traversal source ID, payload over 5 MiB, invalid JSON, future timestamp over ten minutes, source mismatch, root/admin browser upload, non-admin rejection, and last-valid-snapshot preservation.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `bash tools/test_server_monitor_backend.sh tests/test_server_monitor_ingest.py tests/test_compose_integrity.py`

- [ ] **Step 3: Implement token verification and atomic ingestion**

```python
class IngestUnauthorized(RuntimeError):
    pass

def verify_source_token(source_id: str, token: str, token_hashes: dict[str, str]) -> None:
    expected = token_hashes.get(source_id)
    actual = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if expected is None or not hmac.compare_digest(expected, actual):
        raise IngestUnauthorized(source_id)

def atomic_write_snapshot(target: Path, payload: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    lock_path = target.with_suffix(target.suffix + ".lock")
    with lock_path.open("a+") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
        try:
            temporary.write_bytes(payload)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
```

Sanitize external identity fields before writing normalized history. Persist audit JSON lines containing source, timestamp, checksum, result, and error class only.

- [ ] **Step 4: Add relay and browser routes with separate authentication**

Relay route: `POST /api/server-monitor/ingest/{source_id}` using `X-Server-Monitor-Token` and no JWT dependency. Browser route: `POST /api/server-monitor/snapshots/{source_id}/upload` using `get_current_user` and role in `{root, admin}`.

- [ ] **Step 5: Add the narrow writable mount**

Mount `./var/server-monitor-ingest:/app/var/server-monitor-ingest:rw`; keep `./var/artifacts:/app/var/artifacts:ro`. Configure `SERVER_MONITOR_INGEST_DIR` and `SERVER_MONITOR_INGEST_TOKEN_FILE` under `/app/var/config`.

- [ ] **Step 6: Run tests and commit**

Run: `bash tools/test_server_monitor_backend.sh tests/test_server_monitor_ingest.py tests/test_compose_integrity.py tests/test_route_integrity.py`

```bash
git add backend docker-compose.prod.yml
git commit -m "feat: add secure server snapshot ingestion"
```

### Task 6: Standardize the Collector and Node21 Synchronization

**Files:**
- Modify: `tools/server_monitor/collect_server_status.py`
- Create: `tools/server_monitor/sync_sources.py`
- Create: `tools/server_monitor/install_remote_collector.sh`
- Create: `tools/server_monitor/server-monitor-sync.logrotate`
- Create: `backend/tests/test_server_monitor_tools.py`

- [ ] **Step 1: Write failing CLI and dry-run tests**

Test collector argument parsing, version-2 envelope metadata, stdout mode without file writes, sync catalog filtering, local transport, rsync argument construction with timeouts, per-source lock names, and dry-run output.

- [ ] **Step 2: Run tests and verify RED**

Run: `bash tools/test_server_monitor_backend.sh tests/test_server_monitor_tools.py`

- [ ] **Step 3: Refactor collector output without changing scheduler parsing**

```python
def build_envelope(payload: dict, physical_server_id: str, account_id: str, source_id: str) -> dict:
    return {
        "schema_version": 2,
        "collector_version": COLLECTOR_VERSION,
        "physical_server_id": physical_server_id,
        "account_id": account_id,
        "source_id": source_id,
        "collected_at": payload["updated_at"],
        "payload": payload,
    }
```

Add `--physical-server-id`, `--account-id`, `--source-id`, `--output-dir`, and `--stdout`. Keep current PBS/Slurm/system/GPU functions unchanged in this task.

- [ ] **Step 4: Implement catalog-driven synchronization**

`sync_sources.py` loads only `node21_pull` accounts. `local` transport validates the local collector output; `rsync` transport uses `--timeout=30`, `--contimeout=15`, staging, and atomic replacement. Every source writes `var/log/server-monitor/<source>.json` and a bounded text log.

- [ ] **Step 5: Run tests and commit**

Run: `bash tools/test_server_monitor_backend.sh tests/test_server_monitor_tools.py`

```bash
git add tools/server_monitor backend/tests/test_server_monitor_tools.py
git commit -m "feat: standardize server monitor collection"
```

### Task 7: Add the Windows Interactive Relay

**Files:**
- Create: `tools/server_monitor/windows/Sync-ServerMonitorSnapshot.ps1`
- Create: `tools/server_monitor/windows/README.md`
- Modify: `backend/tests/test_server_monitor_tools.py`

- [ ] **Step 1: Add integrity tests before writing the script**

Assert the script contains no literal password, private-key material, MFA seed, or bearer token; requires a catalog source ID; supports `-Preflight`, `-DryRun`, and `-SnapshotPath`; uses Windows Credential Manager through `Get-StoredCredential`; and deletes temporary files in `finally`.

- [ ] **Step 2: Run tests and verify RED**

Run: `bash tools/test_server_monitor_backend.sh tests/test_server_monitor_tools.py`

- [ ] **Step 3: Implement the relay control flow**

```powershell
param(
  [Parameter(Mandatory=$true)][string]$SourceId,
  [switch]$Preflight,
  [switch]$DryRun,
  [string]$SnapshotPath
)
$ErrorActionPreference = 'Stop'
$tempFile = Join-Path $env:TEMP ("matflow-server-monitor-{0}.json" -f [guid]::NewGuid())
try {
  $source = Get-ConfiguredSource -SourceId $SourceId
  if ($Preflight) { Invoke-SshPreflight -Source $source; return }
  if ($SnapshotPath) { Copy-Item -LiteralPath $SnapshotPath -Destination $tempFile }
  else { Invoke-RemoteSnapshot -Source $source -Destination $tempFile }
  Test-SnapshotFile -Path $tempFile -Source $source
  if (-not $DryRun) { Send-MatFlowSnapshot -Source $source -Path $tempFile }
} finally {
  Remove-Item -LiteralPath $tempFile -Force -ErrorAction SilentlyContinue
}
```

Remote SSH authentication remains interactive. Only the source-scoped MatFlow token is retrieved from Windows Credential Manager.

The README includes the one-time dependency and credential commands:

```powershell
Install-Module CredentialManager -Scope CurrentUser
$credential = Get-Credential -UserName 'Dongfang-xjwu' -Message 'Enter the scoped MatFlow ingestion token as the password'
New-StoredCredential -Target 'MatFlow:server-monitor:Dongfang-xjwu' -UserName 'Dongfang-xjwu' -Password $credential.GetNetworkCredential().Password -Persist LocalMachine
```

The README lists the corresponding target command for every `windows_relay` source. The token value is entered interactively on the user's machine and never committed.

- [ ] **Step 4: Verify PowerShell parsing and commit**

Run: `pwsh -NoProfile -Command "[void][scriptblock]::Create((Get-Content -Raw tools/server_monitor/windows/Sync-ServerMonitorSnapshot.ps1))"`

Run: `bash tools/test_server_monitor_backend.sh tests/test_server_monitor_tools.py`

```bash
git add tools/server_monitor/windows backend/tests/test_server_monitor_tools.py
git commit -m "feat: add interactive Windows snapshot relay"
```

### Task 8: Add Shared Frontend Models, Components, and Responsive Styles

**Files:**
- Create: `frontend/src/pages/server_monitor/serverMonitorApi.js`
- Create: `frontend/src/pages/server_monitor/serverMonitorModel.js`
- Create: `frontend/src/pages/server_monitor/ServerMonitor.css`
- Create: `frontend/src/pages/server_monitor/ServerHealthBadge.jsx`
- Create: `frontend/src/pages/server_monitor/ServerAccountList.jsx`
- Modify: `frontend/src/pages/server_monitor/ServerMonitorLayout.jsx`
- Create: `frontend/tests/serverMonitorModel.test.mjs`
- Create: `frontend/tests/serverMonitorPresentation.test.mjs`

- [ ] **Step 1: Write model and presentation tests**

Test physical-server sorting by attention/freshness/name, account labels including `account_unconfirmed`, global/lab metric separation, filter option generation without external users, and CSS minimum font sizes and 720 px mobile breakpoint.

- [ ] **Step 2: Run frontend tests and verify RED**

Run: `npm test`

Expected: missing module/CSS failures.

- [ ] **Step 3: Implement pure view-model helpers**

```javascript
export function sortPhysicalServers(items) {
  const rank = { inconsistent: 0, connection_failed: 1, stale: 2, delayed: 3, pending_setup: 4, normal: 5 };
  return [...items].sort((a, b) =>
    (rank[a.health] ?? 99) - (rank[b.health] ?? 99) ||
    String(a.display_name).localeCompare(String(b.display_name), 'zh-CN')
  );
}

export function accountLabel(account) {
  return account.setup_state === 'account_unconfirmed' ? '账号待确认' : account.display_name;
}
```

- [ ] **Step 4: Implement CSS and shared components**

Use Lucide icons, 8 px-or-less radii for operational surfaces, 24-26 px page titles, 15-16 px member names, 13-14 px body/control text, stable grid tracks, and a full-width mobile layout. Do not render a mobile preview inside desktop DOM.

- [ ] **Step 5: Replace `SERVER_OPTIONS` with API-derived physical servers**

Fetch `/server-monitor/physical-servers` once through a module-level cached promise, append entry and users-overview commands, and render physical IDs rather than legacy source IDs.

- [ ] **Step 6: Run tests/build and commit**

Run: `npm test && npm run build`

```bash
git add frontend/src/pages/server_monitor frontend/tests
git commit -m "feat: add server monitor frontend foundations"
```

### Task 9: Rebuild the Server Monitor Operations Board

**Files:**
- Modify: `frontend/src/pages/server_monitor/ServerMonitorEntry.jsx`
- Modify: `frontend/src/pages/server_monitor/ServerMonitor.css`
- Modify: `frontend/tests/serverMonitorPresentation.test.mjs`

- [ ] **Step 1: Add failing source-level presentation tests**

Assert the entry page renders summary labels for physical servers, accounts, automatic sources, and attention states; renders `ServerAccountList`; contains no legacy large hero gradient; and uses physical IDs for navigation.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --test --test-name-pattern="server monitor" tests/serverMonitorPresentation.test.mjs`

- [ ] **Step 3: Implement the compact operations board**

Render current sources first and stale/manual sources second. Each physical row shows global resource truth, anonymous total load, lab usage, freshness, and expandable account states. Add filters for health and collection mode plus a search field. Do not nest cards or duplicate resource metrics under accounts.

- [ ] **Step 4: Run tests/build and commit**

Run: `npm test && npm run build`

```bash
git add frontend/src/pages/server_monitor/ServerMonitorEntry.jsx frontend/src/pages/server_monitor/ServerMonitor.css frontend/tests/serverMonitorPresentation.test.mjs
git commit -m "feat: rebuild server monitor operations board"
```

### Task 10: Rebuild the Allowlisted Users Overview

**Files:**
- Modify: `frontend/src/pages/server_monitor/ServerMonitorUsersOverview.jsx`
- Modify: `frontend/src/pages/server_monitor/ServerMonitor.css`
- Modify: `frontend/tests/serverMonitorModel.test.mjs`
- Modify: `frontend/tests/serverMonitorPresentation.test.mjs`

- [ ] **Step 1: Write failing worktable tests**

Test range/server/account/member/freshness filtering, canonical aliases, physical-server coverage count, reliable-account attribution only, member/coverage/trend tabs, and absence of an “all scheduler users” option.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --test --test-name-pattern="users overview" tests/serverMonitorModel.test.mjs tests/serverMonitorPresentation.test.mjs`

- [ ] **Step 3: Implement the member worktable**

Use `/users-overview-v2`. Render compact summary metrics, filter controls, a table-first desktop view, expandable server/account details, coverage and trend tabs, and explicit allowlist scope. Remove repeated user cards, duplicate matrix, and progress bars that treat accounts as servers.

- [ ] **Step 4: Implement the 390 px mobile layout**

At `max-width: 720px`, hide secondary columns, preserve member name/aliases/task counts/server labels, make controls horizontally scrollable or wrap without clipping, and open full detail inline.

- [ ] **Step 5: Run tests/build and commit**

Run: `npm test && npm run build`

```bash
git add frontend/src/pages/server_monitor/ServerMonitorUsersOverview.jsx frontend/src/pages/server_monitor/ServerMonitor.css frontend/tests
git commit -m "feat: rebuild server users overview"
```

### Task 11: Convert Server Detail and Add Manual Upload UI

**Files:**
- Modify: `frontend/src/pages/server_monitor/ServerMonitorPage.jsx`
- Modify: `frontend/src/pages/server_monitor/ServerMonitorEntry.jsx`
- Modify: `frontend/src/pages/server_monitor/serverMonitorApi.js`
- Modify: `frontend/src/pages/server_monitor/ServerMonitor.css`
- Modify: `frontend/tests/serverMonitorPresentation.test.mjs`

- [ ] **Step 1: Write failing detail/upload tests**

Assert the detail route fetches by physical ID, shows global resource and lab usage sections, shows account status without duplicate resources, displays inconsistency/stale warnings, and exposes snapshot upload only for localStorage user roles `root` or `admin`.

- [ ] **Step 2: Run tests and verify RED**

Run: `node --test --test-name-pattern="server detail" tests/serverMonitorPresentation.test.mjs`

- [ ] **Step 3: Implement physical detail and upload dialog**

Use `/physical/{id}` and `/physical/{id}/usage`. The upload action accepts one `.json` file, requires explicit source selection, posts multipart form data, reports validation errors, and refreshes the affected physical row after success.

- [ ] **Step 4: Run tests/build and commit**

Run: `npm test && npm run build`

```bash
git add frontend/src/pages/server_monitor frontend/tests/serverMonitorPresentation.test.mjs
git commit -m "feat: update physical server detail and uploads"
```

### Task 12: Add Safe Frontend Deployment and Expand Backend Preflight

**Files:**
- Create: `tools/deploy_frontend_safely.sh`
- Modify: `tools/deploy_backend_safely.sh`
- Modify: `backend/tests/test_deploy_script_integrity.py`

- [ ] **Step 1: Write failing deploy integrity tests**

Assert frontend deploy requires the canonical checkout, runs `npm test`, builds the Nginx image, preserves the previous image tag, verifies Nginx config and public routes, and restores the previous image on failure. Assert backend deploy runs every new server-monitor test and prewarms version-2 overview ranges.

- [ ] **Step 2: Run tests and verify RED**

Run: `bash tools/test_server_monitor_backend.sh tests/test_deploy_script_integrity.py`

- [ ] **Step 3: Implement safe frontend deployment**

Follow the backend script's canonical-root, image capture, rollback trap, health wait, TLS-verified public probes, and final evidence output. Recreate only `nginx`; do not rebuild backend in this script.

- [ ] **Step 4: Expand backend deployment checks**

Run catalog/scopes/snapshots/API/ingest/tool tests before build, create the ingestion directory with restrictive permissions, validate token-file presence without printing it, and prewarm all version-2 ranges after health passes.

- [ ] **Step 5: Run integrity tests and commit**

Run: `bash tools/test_server_monitor_backend.sh tests/test_deploy_script_integrity.py tests/test_compose_integrity.py`

```bash
git add tools/deploy_frontend_safely.sh tools/deploy_backend_safely.sh backend/tests
git commit -m "chore: harden server monitor deployment"
```

### Task 13: Install the New HFNL Account and Replace Pull Orchestration

**Files:**
- Production data/config only after code review; no unreviewed repository file changes.

- [ ] **Step 1: Back up collection state**

Create a timestamped backup of `var/artifacts/server_monitor/sync_all.sh`, the eight reachable remote collector files, current crontabs, and `var/artifacts/server_monitor` status metadata. Do not copy the complete historical tree.

- [ ] **Step 2: Dry-run every node21 source**

Run: `python3 tools/server_monitor/sync_sources.py --dry-run --all`

Expected: all current reachable sources resolve; `Shuangyiliu-HFNL-wjb` reports pending setup rather than failure.

- [ ] **Step 3: Install and validate the `wjb` collector**

```bash
ssh wjb@114.214.207.167 'mkdir -p /share/home/wjb/server_monitor'
bash tools/server_monitor/install_remote_collector.sh \
  --login wjb@114.214.207.167 \
  --remote-dir /share/home/wjb/server_monitor \
  --physical-server-id shuangyiliu-hfnl \
  --account-id wjb \
  --source-id Shuangyiliu-HFNL-wjb
```

Run one remote collection, validate JSON/schema/source identity, then verify the cron entry. If the actual home is not `/share/home/wjb`, derive it with `ssh ... 'printf %s "$HOME"'` and pass that returned absolute path; do not guess or write outside the returned home.

- [ ] **Step 4: Roll out remaining reachable collectors one source at a time**

For each source: back up remote script, install, run once, compare resource/job fields with the previous snapshot, confirm next cron run, then continue. Stop on the first mismatch.

- [ ] **Step 5: Replace the node21 cron target with the compatibility wrapper**

Run the new wrapper manually twice, confirm lock behavior and bounded logs, then update the existing `*/10` cron line. Preserve the old script in the timestamped backup for rollback.

### Task 14: Full Verification, Production Deployment, and Browser Acceptance

**Files:**
- No new feature files; only fixes discovered by verification.

- [ ] **Step 1: Run the complete backend suite in the isolated remote worktree**

```bash
docker run --rm \
  -e JWT_SECRET=test-only-server-monitor-secret \
  -e LMATELAB_DATA_DIR=/tmp/lmatelab-test-var \
  -v "$PWD/backend:/app" -w /app lmatelab-backend \
  sh -lc 'pip install -q pytest && python -m pytest -q tests'
```

Expected: zero failures.

- [ ] **Step 2: Run frontend tests and production build**

Run in `frontend`: `npm test && npm run build`.

Expected: zero test failures and Vite exit 0.

- [ ] **Step 3: Review code and secrets before merge**

Run `git diff master...HEAD --check`, search for passwords/tokens/private keys, inspect all new writable paths, and verify legacy artifacts remain read-only. Resolve every finding before deployment.

- [ ] **Step 4: Fast-forward production master and deploy backend first**

Use a clean production checkout, preserve the existing pre-merge stash, fast-forward only reviewed commits, then run `tools/deploy_backend_safely.sh`. Verify old and new authenticated endpoints before changing Nginx/frontend.

- [ ] **Step 5: Deploy frontend through the safe script**

Run `tools/deploy_frontend_safely.sh`. Verify `/`, `/dashboard`, `/api/health/live`, and `/api/health/ready` return 200 with TLS verification.

- [ ] **Step 6: Exercise the target browser flows with Playwright CLI**

The flow under test is: sign in -> open server monitor -> expand each confirmed multi-account physical server -> inspect global/lab metrics -> open users overview -> filter range/server/member -> verify mobile layout -> upload a test snapshot as root -> observe refreshed status.

Use desktop `1536x960` and mobile `390x844`. Check URL/title, meaningful DOM, no framework overlay, console warnings/errors, clipping/overlap, and interaction state. Capture consecutive screenshots outside the repository.

- [ ] **Step 7: Verify the critical statistical invariant against live data**

For at least one shared server with external load, compare API `resource_summary.node_busy/node_free` to the source scheduler node state and verify the lab summary excludes external identities without increasing free capacity.

- [ ] **Step 8: Verify source/account inventory**

Confirm:

```text
双一流微尺度 -> xjwu, hflv, wjb
东方超算 -> xjwu, yang4
精准平台 -> xjwu, jbwu
精准平台 GPU -> separate physical server
```

- [ ] **Step 9: Clean temporary state and report residual limitations**

Remove the remote implementation worktree after merge, close Playwright, retain rollback tags/backups, and report which isolated sources passed Windows SSH preflight. A source requiring interactive MFA remains manual-triggered and must not be described as unattended.

## Spec Coverage Self-Check

- Physical server/account/member separation: Tasks 1, 3, 4, 8-11.
- Confirmed three multi-account groups and separate Jingzhun GPU: Tasks 1, 13, 14.
- Strict 28-account allowlist and external identity suppression: Tasks 1, 2, 4, 10.
- Accurate global resource occupancy including external load: Tasks 2, 3, 11, 14.
- Shared-snapshot deduplication and conflict warning: Tasks 3, 4, 9.
- Node21 pull, new `wjb` setup, bounded logs: Tasks 6, 13.
- Windows relay and browser fallback: Tasks 5, 7, 11.
- Larger desktop/mobile UI and compact operations layout: Tasks 8-11, 14.
- Backward-compatible rollout, cache handling, rollback: Tasks 4, 5, 12, 14.
- Security and test acceptance: Tasks 5, 7, 12, 14.
