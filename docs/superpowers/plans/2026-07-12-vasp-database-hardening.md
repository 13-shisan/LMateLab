# VASP Database Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the eight reviewed VASP database issues in severity order and verify desktop/mobile behavior against live data.

**Architecture:** Add focused backend schema/query helpers and a focused frontend task-table component. Preserve existing ASE files and URL parameters, add compatible query capabilities, and keep PBS ingestion guarded from the web host.

**Tech Stack:** FastAPI, ASE SQLite, Python unittest, React, CSS, Node test runner, Vite, Playwright CLI, Docker Compose

---

### Task 1: Data visibility and owner truth

**Files:**
- Create: `backend/tests/test_vasp_table_contract.py`
- Modify: `backend/routers/vasp_db.py`
- Modify: `backend/authz_db.py`
- Modify: `var/data/allowed_users.json`
- Modify: `frontend/src/pages/db/PersonalVaspDatabase.jsx`

- [x] Add failing tests requiring owner availability to reflect resolved database files and requiring table markup to avoid fixed height plus vertical clipping.
- [x] Correct `Pwjx` to its existing generated database; leave `Pzxp` and `Psxz` unavailable because no replacement database file exists.
- [x] Return owner source metadata and render missing owners disabled with an explicit reason.
- [x] Remove `TABLE_ROW_H`, `TABLE_HEAD_H`, fixed table height, and vertical `overflow: hidden`.
- [x] Run focused backend/frontend tests and verify RED then GREEN.

### Task 2: Column presentation and responsive task surface

**Files:**
- Create: `backend/services/vasp_table_schema.py`
- Create: `frontend/src/pages/db/vaspTablePresentation.js`
- Create: `frontend/src/pages/db/VaspDataTable.jsx`
- Create: `frontend/src/pages/db/VaspDataTable.css`
- Create: `frontend/tests/vaspTablePresentation.test.mjs`
- Modify: `backend/routers/vasp_db.py`
- Modify: `frontend/src/pages/db/PersonalVaspDatabase.jsx`

- [x] Add failing tests for Chinese labels, units, precision, missing values, and path compaction.
- [x] Define canonical metadata for the default scientific columns and dynamic-column fallback metadata.
- [x] Return metadata from `/columns` and render it through `VaspDataTable`.
- [x] Keep full raw values in title text while rendering bounded scientific precision.
- [x] Add desktop sticky headers and mobile priority rows with an expandable secondary field area.
- [x] Verify returned rows are not hidden by a fixed table viewport.

### Task 3: Freshness, cache correctness, and request flow

**Files:**
- Create: `tools/submit_vasp_dataset_refresh.sh`
- Modify: `backend/routers/vasp_db.py`
- Modify: `frontend/src/pages/db/PersonalVaspDatabase.jsx`
- Modify: `backend/tests/test_vasp_table_contract.py`

- [x] Add failing tests that final-record cache writes are persisted and row/query filters affect file-cache identity.
- [x] Build final-record IDs through SQLite, serialize them atomically, and expand filtered-cache keys.
- [x] Cache `/columns` responses by refs, mtimes, sample, mode, and element selection.
- [x] Return latest source mtime/stale state and display it near the database selector.
- [x] Add a PBS-only submission wrapper that validates `qsub`, the working directory, and duplicate queued jobs before submission.
- [x] Gate tasks fetching until columns/default selection is initialized so one route load issues one effective tasks request.

### Task 4: Ordering, search, and mode clarity

**Files:**
- Modify: `backend/routers/vasp_db.py`
- Modify: `frontend/src/pages/db/PersonalVaspDatabase.jsx`
- Modify: `frontend/src/pages/db/VaspDataTable.jsx`
- Modify: `backend/tests/test_vasp_table_contract.py`

- [x] Add failing tests for newest/oldest ID ordering and numeric/formula search.
- [x] Add validated `sort_order=desc|asc` and `query` parameters to `/tasks`.
- [x] Preserve `only_last`, but replace technical checkbox copy with a two-option mode control.
- [x] Initialize absent URLs to `only_last=1`, `sort_order=desc`, and keep explicit legacy URLs unchanged.
- [x] Debounce search, reset to page one, and keep all state in the URL.

### Task 5: Full verification and deployment

**Files:**
- Modify only files required by failures discovered during verification.

- [x] Run backend unit tests, frontend tests, focused ESLint, production build, and `git diff --check`.
- [x] Deploy backend and nginx with the existing safe production workflow.
- [x] Verify live desktop at 1440x1000 and mobile at 390x844: 20 visible rows, no document overflow, readable labels, working mode/search/sort, and zero relevant console errors.
- [x] Verify `/api/health/live` and container health.
- [x] Report the PBS submission-host blocker because `qsub` remains unavailable; do not run the ingestion job on the web host.
