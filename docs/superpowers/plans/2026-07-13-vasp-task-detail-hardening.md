# VASP Task Detail Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a secure, responsive VASP task-detail page whose 3D viewer stays in bounds, scientific outputs load only when available and requested, and list actions accurately describe their behavior.

**Architecture:** Add a pure backend payload/capability service and keep authorization/path resolution in the router. Refactor the React route into focused detail components, bundle a pinned 3Dmol dependency, and let CSS own all responsive geometry. Use contract tests for payload exposure and source tests plus production/browser checks for rendering behavior.

**Tech Stack:** FastAPI, ASE, Python unittest/pytest, React, Vite, CSS, 3dmol 2.5.5, Node test runner, Playwright CLI, Docker Compose

---

### Task 1: Backend detail contract and capability detection

**Files:**
- Create: `backend/services/vasp_task_detail.py`
- Create: `backend/tests/test_vasp_task_detail_contract.py`
- Modify: `backend/routers/vasp_db.py`

- [ ] **Step 1: Write failing contract tests**

Create real fake-row tests which require `build_public_task_detail()` to expose only `id`, `formula`, `energy`, `fmax`, `natoms`, and `pbc`; map four physical properties; omit `data`, `source_dir`, and calculator parameters; and produce capability booleans from `has_vasprun`/`has_outcar`.

```python
payload = build_public_task_detail(
    row=FakeRow(data={"source_dir": "/storage/private", "phys_bandgap_eV": 1.2}),
    db={"key": "personal:jbwu:Pwjb.db", "dbname": "Pwjb.db"},
    has_vasprun=False,
    has_outcar=False,
)
self.assertNotIn("data", payload["row"])
self.assertNotIn("source_dir", json.dumps(payload))
self.assertFalse(payload["capabilities"]["band_plot"])
```

- [ ] **Step 2: Run the focused backend test and confirm RED**

Run: `cd backend && python3 -m pytest -q tests/test_vasp_task_detail_contract.py`

Expected: import failure for `services.vasp_task_detail`.

- [ ] **Step 3: Implement the pure payload builder**

Implement allowlisted row/property serialization and one capability function. `structure_export` is always true for a resolved ASE row; band/DOS plot and data flags are true only when a vasprun or OUTCAR source exists.

- [ ] **Step 4: Wire the router contract and HTTP semantics**

Update `/task/{row_id}/detail` to:

```python
if not ref.exists:
    raise HTTPException(status_code=404, detail=_missing_detail(ref))
row = con.get(id=row_id)
if row is None:
    raise HTTPException(status_code=404, detail="row not found")
```

Resolve source files through `_mnt_join_source_dir`, `_assert_allowed_task_path`, and `_pick_vasp_files`; convert validation/missing-directory failures to all-false electronic capabilities without exposing the path. Build the response through the pure service. Remove `workdir` from successful band/DOS JSON responses and the public workdir route response.

- [ ] **Step 5: Run backend tests and confirm GREEN**

Run: `cd backend && python3 -m pytest -q tests/test_vasp_task_detail_contract.py tests/test_vasp_table_contract.py`

Expected: all focused tests pass.

### Task 2: Frontend contract tests and pinned 3Dmol dependency

**Files:**
- Create: `frontend/tests/vaspTaskDetailPresentation.test.mjs`
- Create: `frontend/src/pages/db/vasp-detail/vaspTaskDetailPresentation.js`
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Modify: `frontend/index.html`

- [ ] **Step 1: Write failing presentation/source tests**

Require Chinese labels and bounded numeric precision, assert `frontend/index.html` no longer references `https://3Dmol.org`, assert the new CSS contains a relative viewer host and a 700px mobile breakpoint, and assert the table action source contains `输入参数` instead of a generic `详情` label.

- [ ] **Step 2: Run the Node test and confirm RED**

Run: `cd frontend && npm test -- --test-name-pattern="VASP task detail"`

Expected: module/file assertions fail because the new presentation module and CSS do not exist.

- [ ] **Step 3: Add presentation helpers and dependency**

Implement `TASK_FIELD_PRESENTATION` plus `formatTaskValue(key, value)` returning `-` for missing values and fixed decimal strings for scientific values. Install exactly `3dmol@2.5.5` with `npm install --save-exact 3dmol@2.5.5`. Remove the runtime CDN script from `frontend/index.html`.

- [ ] **Step 4: Run the focused test**

Run: `cd frontend && npm test -- --test-name-pattern="VASP task detail"`

Expected: presentation/dependency assertions pass; layout/component assertions may remain RED until Tasks 3-5.

### Task 3: Stable structure viewer component

**Files:**
- Create: `frontend/src/pages/db/vasp-detail/VaspStructureViewer.jsx`
- Create: `frontend/src/pages/db/vasp-detail/VaspTaskDetail.css`
- Modify: `frontend/tests/vaspTaskDetailPresentation.test.mjs`

- [ ] **Step 1: Add source assertions for lifecycle and bounds**

Require dynamic `import("3dmol")`, `ResizeObserver`, viewer cleanup, `.vasp-structure-viewer { position: relative; overflow: hidden; }`, and bounded mobile dimensions.

- [ ] **Step 2: Run tests and confirm RED for missing component**

Run: `cd frontend && npm test -- --test-name-pattern="VASP task detail"`

- [ ] **Step 3: Implement the viewer**

The component dynamically imports 3dmol, constructs XYZ, applies element colors, cell edges, and axes, calls `zoomTo()`/`render()`, and resizes through a `ResizeObserver`. It must render loading/import/render errors inside the host and clean observers/viewer DOM on record changes or unmount.

- [ ] **Step 4: Run tests and Vite build**

Run: `cd frontend && npm test -- --test-name-pattern="VASP task detail" && npm run build`

Expected: focused tests pass and Vite resolves the pinned 3dmol package.

### Task 4: Summary and crystal-detail components

**Files:**
- Create: `frontend/src/pages/db/vasp-detail/VaspTaskSummary.jsx`
- Create: `frontend/src/pages/db/vasp-detail/VaspCrystalDetails.jsx`
- Modify: `frontend/src/pages/db/vasp-detail/VaspTaskDetail.css`

- [ ] **Step 1: Extend source tests for responsive grids**

Require summary and crystal grids to use named CSS classes and require the mobile media query to collapse each class to one column without fixed page widths.

- [ ] **Step 2: Run tests and confirm RED**

Run: `cd frontend && npm test -- --test-name-pattern="VASP task detail"`

- [ ] **Step 3: Implement summary**

Render Chinese labels, formatted values, database name, element swatches, and capability-aware structure/band/DOS exports. Catch download failures and expose one visible action error.

- [ ] **Step 4: Implement crystal details**

Render lattice, density/dimensionality/spacegroup, and the fractional-coordinate table. Preserve ten-row collapse/expand behavior and wrap the table in its own horizontal scroller.

- [ ] **Step 5: Run focused tests**

Run: `cd frontend && npm test -- --test-name-pattern="VASP task detail"`

Expected: responsive component source tests pass.

### Task 5: Capability-aware electronic properties

**Files:**
- Create: `frontend/src/pages/db/vasp-detail/VaspElectronicProperties.jsx`
- Modify: `frontend/src/pages/db/vasp-detail/VaspTaskDetail.css`
- Modify: `frontend/tests/vaspTaskDetailPresentation.test.mjs`

- [ ] **Step 1: Add failing lazy-load tests/source assertions**

Require plot URLs to be constructed only inside the active-tab effect, the effect to depend on the active tab and capability booleans, and unavailable tabs to be disabled. Assert there is no eager sequential band-then-DOS effect in the route component.

- [ ] **Step 2: Run tests and confirm RED**

Run: `cd frontend && npm test -- --test-name-pattern="VASP task detail"`

- [ ] **Step 3: Implement lazy plot loading**

Choose the first available tab, fetch only the active available plot, retain successful base64 images in component state, and avoid repeated requests. Display a neutral `该记录没有可用的能带或 DOS 源文件` state when both are unavailable. Keep plot errors local and capability-aware exports disabled.

- [ ] **Step 4: Run focused tests and build**

Run: `cd frontend && npm test -- --test-name-pattern="VASP task detail" && npm run build`

Expected: tests and build pass.

### Task 6: Route orchestration and accurate table action

**Files:**
- Rewrite: `frontend/src/pages/db/VaspTaskDetail.jsx`
- Modify: `frontend/src/pages/db/VaspDataTable.jsx`
- Modify: `frontend/src/pages/db/PersonalVaspDatabase.jsx`
- Modify: `frontend/src/pages/db/vasp-detail/VaspTaskDetail.css`
- Modify: `frontend/tests/vaspTaskDetailPresentation.test.mjs`

- [ ] **Step 1: Add failing route-source assertions**

Require the route to import all four focused components, use the compact section navigation, render loading/403/404 states, and contain no fixed `240px 1fr`, fixed 460px viewer, `window.$3Dmol`, eager plot state, or disabled phonon control.

- [ ] **Step 2: Run tests and confirm RED**

Run: `cd frontend && npm test -- --test-name-pattern="VASP task detail"`

- [ ] **Step 3: Rewrite the route orchestrator**

Fetch only the reduced detail endpoint, classify fetch errors by status, preserve exact back navigation, and compose the page header, in-page navigation, structure surface, crystal details, and electronic properties. Keep all route parameters encoded.

- [ ] **Step 4: Rename the list action**

Change the calculator-parameter button copy from `详情` to `输入参数`, retain the row ID link as the full-page entry, and update modal title copy to `输入参数` without changing the endpoint.

- [ ] **Step 5: Run complete frontend verification**

Run: `cd frontend && npm test && npx eslint src/pages/db/VaspTaskDetail.jsx src/pages/db/VaspDataTable.jsx src/pages/db/vasp-detail/*.jsx src/pages/db/vasp-detail/*.js && npm run build`

Expected: all Node tests, focused ESLint, and build pass.

### Task 7: Server verification, deployment, and live QA

**Files:**
- Modify only files required by failures discovered during verification.

- [ ] **Step 1: Run local diff and contract verification**

Run: `git diff --check && git status --short` plus the focused backend/frontend commands from Tasks 1 and 6.

- [ ] **Step 2: Synchronize to canonical production checkout**

Normalize modified text files to LF, copy only the reviewed files to `/home/software/LMateLab`, and verify remote `git diff --check` before deployment.

- [ ] **Step 3: Run server tests and builds**

Run backend focused tests and Python compile checks, then frontend tests, focused ESLint, and Vite build on the server.

- [ ] **Step 4: Deploy backend and frontend**

Run `tools/deploy_backend_safely.sh`, verify backend health, build the Nginx service, recreate only Nginx, and verify public HTTP 200. Preserve rollback image tags.

- [ ] **Step 5: Desktop browser QA**

At 1440x1000 on record 237943 verify page identity, nonblank content, canvas contained by viewer, no document overflow, no band/DOS requests for false capabilities, no relevant console errors, coordinates expansion, export menu, and return navigation.

- [ ] **Step 6: Mobile browser QA**

At 390x844 verify `scrollWidth === clientWidth`, the viewer is within viewport bounds, all grids are one column, section navigation stays within its scroller, and scientific tables do not widen the document.

- [ ] **Step 7: Verify list interaction**

Return to the filtered VASP list, click `输入参数`, verify the calculator-parameters modal opens, close it, then click the record ID and verify the full task route opens.

- [ ] **Step 8: Commit, push, and confirm clean production state**

Commit the verified implementation, push to `master`, ensure the production checkout is clean, and record the deployed commit plus container/public health evidence.
