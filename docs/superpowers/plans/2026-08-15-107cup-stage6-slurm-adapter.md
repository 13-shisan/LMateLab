# 107 Cup Stage 6 Slurm Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed, database-backed Slurm adapter for ordinary 107 Cup probe jobs, including state observation, cancellation ownership checks and restart reconciliation, without running VASP.

**Architecture:** Keep scheduler process execution in `competition_slurm.py` and database transitions in `competition_reconcile.py`. Use structured Slurm JSON where available, fixed argv-only commands, an attempt receipt for crash recovery, and the existing workflow tables for the ledger. Expose stored attempt evidence and owned cancellation through the existing competition router; reserve scientific submission for Stage 7.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy 2, SQLite, `unittest`, Slurm 25.11 JSON CLI, Bash, SHA-256 evidence manifests.

---

### Task 1: Define the Slurm command and state contract

**Files:**
- Create: `backend/services/competition_slurm.py`
- Create: `backend/tests/test_competition_slurm.py`
- Create: `backend/tests/fixtures/fake_slurm/squeue-running.json`
- Create: `backend/tests/fixtures/fake_slurm/scontrol-running.json`
- Create: `backend/tests/fixtures/fake_slurm/scontrol-completed.json`

- [x] Write failing tests for absolute fixed binaries, argv-only calls, bounded
      timeouts, `sbatch --test-only`, `sbatch --parsable` Job ID parsing and
      malformed/oversized output.
- [x] Run `backend/.venv/Scripts/python.exe -m unittest tests.test_competition_slurm -v`
      and confirm RED because the module does not exist.
- [x] Implement the injectable runner and typed exceptions without `shell=True`.
- [x] Add failing fixture-based tests for queued, running, completing, succeeded,
      failed, cancelled and unknown Slurm states, retaining raw state, exit code,
      reason, source, node and observation timestamp.
- [x] Implement JSON parsing for `squeue` and `scontrol`; add optional `sacct`
      parsing that reports accounting unavailable without hiding live evidence.
- [x] Run the focused suite and commit the green command/state boundary.

### Task 2: Constrain working directories, receipts and logs

**Files:**
- Modify: `backend/services/competition_slurm.py`
- Modify: `backend/tests/test_competition_slurm.py`

- [x] Write failing tests for traversal, sibling-prefix paths, absolute
      user-supplied paths, symlinks and reads larger than the configured tail.
- [x] Implement resolved-root containment, private directory creation, atomic
      `job-id.receipt` writes and bounded `stdout.log`/`stderr.log` tail reads.
- [x] Verify the tests fail before implementation and pass afterward.
- [x] Commit the filesystem boundary.

### Task 3: Add database-backed attempt submission and recovery

**Files:**
- Create: `backend/services/competition_reconcile.py`
- Modify: `backend/tests/test_competition_slurm.py`
- Modify: `backend/services/competition_workflows.py`

- [x] Write failing tests that only one session can claim the first waiting step
      of a validated workflow and that an attempt ledger exists before `sbatch`.
- [x] Implement the SQLite-safe claim, attempt directory, canonical JobName and
      exact comment construction.
- [x] Write failing tests for scheduler rejection, Job ID receipt recovery,
      database failure after scheduler acceptance and duplicate submission.
- [x] Implement submission finalization and exact scheduler recovery without
      submitting arbitrary scripts or options.
- [x] Record monotonic workflow events for submission accepted, failed and
      uncertain outcomes.
- [x] Run workflow plus Slurm suites and commit the submission ledger.

### Task 4: Implement ownership-gated cancellation

**Files:**
- Modify: `backend/services/competition_slurm.py`
- Modify: `backend/services/competition_reconcile.py`
- Modify: `backend/tests/test_competition_slurm.py`

- [x] Write one failing test for each required ownership mismatch: JobName,
      WorkDir, exact comment and database Job ID.
- [x] Add tests for missing scheduler metadata, terminal jobs, current-account
      mismatch and the race where a job completes before `scancel`.
- [x] Implement an immediate `scontrol` ownership snapshot followed by
      `scancel <ledger job id>` only when every check passes.
- [x] Preserve the before-cancel snapshot and result in attempt metadata/events.
- [x] Run focused tests and commit the cancellation gate.

### Task 5: Reconcile state across fresh processes

**Files:**
- Modify: `backend/services/competition_reconcile.py`
- Modify: `backend/tests/test_competition_slurm.py`

- [x] Write failing tests for a fresh reconciler reading queued, running,
      completed, failed and cancelled attempts from the same SQLite database.
- [x] Add RED cases where `sacct` is unavailable and the live record disappears;
      expected result is `unknown/stale`, never stale `running` or guessed success.
- [x] Implement idempotent state/event transitions and timestamp updates.
- [x] Cover cancellation/completion races and repeated reconciliation.
- [x] Run focused tests and commit reconciliation.

### Task 6: Expose read evidence and owned cancellation

**Files:**
- Modify: `backend/routers/competition_workflows.py`
- Modify: `backend/tests/test_competition_workflow_routes.py`
- Modify: `backend/tests/test_competition_slurm.py`

- [x] Write failing route tests for latest-attempt serialization in the existing
      workflow timeline fields.
- [x] Write failing route tests proving Viewer and non-owner cancellation are
      forbidden, an arbitrary Job ID cannot be supplied, and scheduler errors
      do not leak paths or command output.
- [x] Implement `POST /competition/workflows/{workflow_id}/attempts/{attempt_id}/cancel`
      using authenticated workflow and attempt ownership.
- [x] Replace dashboard `not-integrated` only with a bounded ledger-derived
      scheduler summary; do not enumerate or expose unrelated shared-account jobs.
- [x] Run workflow route and Slurm suites and commit API integration.

### Task 7: Add the fixed probe and deployment contracts

**Files:**
- Create: `deploy/107cup/slurm/probe.slurm`
- Create: `deploy/107cup/slurm/stage6-smoke.py`
- Modify: `backend/tests/test_107cup_preview_deploy_contract.py`
- Modify: `backend/tests/test_107cup_deploy_contract.py`
- Modify: `deploy/107cup/workflow-preview-build.slurm`
- Modify: `deploy/107cup/build.slurm`

- [x] Write failing contract tests for a fixed competition account, partition,
      QOS, one CPU, small memory/time limits, private umask and allowlisted
      `success|fail|cancel` probe modes.
- [x] Implement the probe without VASP, arbitrary commands or login-node work.
- [x] Add a smoke harness that uses an isolated SQLite database and emits raw
      scheduler evidence plus a SHA-256 manifest.
- [x] Add Stage 6 tests to preview and formal build gates.
- [x] Run `bash -n` for every changed Bash/Slurm file and commit deployment
      contracts.

### Task 8: Run local regression and prepare the feature PR

**Files:**
- Modify: `docs/107cup/implementation-plan.md`

- [ ] Run the focused RED/GREEN suite and the existing Stage 5 backend suites.
- [ ] Run all 107 Cup backend deployment/runtime suites.
- [ ] Run frontend `npm test`; no frontend source change is expected.
- [ ] Run `git diff --check` and scan the diff for secrets, arbitrary command
      execution, `shell=True`, unbounded reads and unrelated feature drift.
- [ ] Update the implementation plan with local-only evidence and keep Stage 6
      `PARTIAL` until merged 107 validation succeeds.
- [ ] Commit, push `codex/107cup-stage6-slurm-adapter`, and create a PR to protected
      `main`.

### Task 9: Validate the merged commit on 107

**Files:**
- Evidence only; do not edit source on 107.

- [ ] After merge, pin the 107 detached checkout to the exact `main` merge commit.
- [ ] Run pre-change snapshot and a Slurm build job; do not build or run tests on
      the login node.
- [ ] Run the fixed Stage 6 smoke from a compute allocation and retain successful,
      failed, cancelled, restart-reconciled and non-owned rejection evidence.
- [ ] Confirm `sbatch --test-only` leaves no residual job and the smoke harness
      cleans up only its explicitly owned foreign control job.
- [ ] Verify stable service, databases, public entry and unrelated jobs remain
      unchanged.
- [ ] Record immutable evidence with SHA-256 and submit a separate evidence PR.

### Task 10: Close Stage 6

**Files:**
- Modify: `docs/107cup/implementation-plan.md`
- Create: `docs/107cup/stage6-slurm-evidence.md`

- [ ] Reconcile every Job ID and retained artifact against the merged commit.
- [ ] Review ownership and failure evidence independently.
- [ ] Mark Stage 6 `DONE` only after the evidence PR is merged and Windows,
      Gitea `main`, and the 107 checkout agree.
- [ ] Keep Stage 7 and Stage 8 `PENDING`; do not run VASP in this plan.
