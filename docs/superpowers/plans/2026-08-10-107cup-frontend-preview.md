# LMateLab 107 Cup Frontend Preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and independently deploy the five-page LMateLab 107 Cup React preview around the fixed `structure -> relax -> SCF -> BAND -> DOS -> results/database/evidence` route, while every preview mutation fails closed and the stable 107 service remains unchanged.

**Architecture:** Keep `App107Cup.jsx` as the isolated competition entry and place all competition pages behind one build-time-selected data provider. Reuse the existing 3D structure, BAND/DOS, VASP formatting, element color, periodic-table, and table capabilities through direct imports or small compatibility extractions; the demo provider supplies version-controlled MoS2 fixtures, while the live provider only defines the future `/api/competition/` contract and is not counted as a working backend. Build and serve the preview in separate Slurm jobs under `previews/$commit` with separate databases, runtime state, port, and evidence, never switching `current`.

**Tech Stack:** React 19, React Router 7, Vite 7, 3Dmol 2.5.5, Recharts/Chart.js, Lucide React, Node `node:test`, Playwright, FastAPI health/auth shell, Python `unittest`, Slurm, Bash, SQLite, SHA-256 manifests.

---

## Scope And Execution Gates

This plan implements only the preview authorized by `docs/superpowers/specs/2026-08-10-107cup-frontend-preview-design.md`.

- The five React surfaces are real UI. Their workflow, Slurm, VASP, and database content is explicitly labelled demo data.
- The live provider defines request shapes only. Missing phase 5-8 backend endpoints must surface a visible error and must not fall back to demo success.
- Upload, draft save, submit, cancel, retry, and database mutation stay disabled in demo mode; the demo provider also rejects direct calls with `PreviewReadOnlyError` before any network request.
- No full `backend/routers/vasp_db.py`, legacy `PersonalVaspDatabase`, Agent, ML, QE/EPW, server monitor, or 4090 production data is exposed by the 107 entry.
- Do not change phase 5, 6, 7, or 8 from `PENDING` during this plan.
- Before implementation, merge this documentation branch through Gitea PR, fast-forward local `main`, and create an isolated `codex/107cup-frontend-preview` worktree from that merged `main`. Do not implement directly on protected `main` or on the documentation branch.
- Before remote deployment, merge the implementation PR to protected `main`. The 107 checkout may fetch only the resulting fixed merge commit with its read-only Deploy Key.
- All dependency installation, tests, builds, and long-running services on 107 run inside Slurm jobs. Login-node helpers may only fetch, submit, query, and read short status/evidence files.

## File Structure

### Frontend Data Boundary

- Create `frontend/src/features/competition/data/competitionErrors.js`: typed preview/read/API errors and HTTP error mapping.
- Create `frontend/src/utils/elementSelection.js`: shared deterministic multi-element selection and matching helpers.
- Create `frontend/src/features/competition/data/demoFixtures.js`: three minimal MoS2 workflow fixtures, structure, plots, database rows, and evidence downloads.
- Create `frontend/public/competition-fixtures/mos2-band-demo.svg`: clearly labelled demo band plot served as a static preview asset.
- Create `frontend/public/competition-fixtures/mos2-dos-demo.svg`: clearly labelled demo DOS plot served as a static preview asset.
- Create `frontend/src/features/competition/data/demoCompetitionDataProvider.js`: query/filter functions and fail-closed mutations without network access.
- Create `frontend/src/features/competition/data/apiCompetitionDataProvider.js`: future live GET/mutation request contract; never falls back to fixtures.
- Create `frontend/src/features/competition/data/competitionDataProvider.js`: build-time `demo|live` selection with invalid-mode failure.
- Create `frontend/src/features/competition/CompetitionDataContext.jsx`: one provider instance and stable query state hook for every competition page.
- Create `frontend/tests/competitionDataProvider.test.mjs`: provider mode, filter, request-path, state/error, and mutation tests.

### Shared Scientific UI

- Create `frontend/src/pages/db/periodicTableElements.js`: the exact 118-element position/name data extracted from the legacy page.
- Create `frontend/src/pages/db/PeriodicTableFilter.jsx`: controlled periodic-table selection component.
- Create `frontend/src/pages/db/PeriodicTableFilter.css`: stable 18-column grid and small-screen horizontal scrolling.
- Create `frontend/src/pages/db/VaspRecordTable.jsx`: read-only responsive VASP table core with configurable detail target.
- Modify `frontend/src/pages/db/PersonalVaspDatabase.jsx`: consume the extracted periodic table without changing legacy API or mutation behavior.
- Modify `frontend/src/pages/db/VaspDataTable.jsx`: retain legacy row actions as a wrapper around `VaspRecordTable`.
- Modify `frontend/src/pages/db/VaspDataTable.css`: make the action column conditional without changing existing desktop/mobile layouts.
- Modify `frontend/src/pages/db/vasp-detail/VaspStructureViewer.jsx`: add a stable reset-view icon and preserve cleanup/error behavior.
- Modify `frontend/src/pages/db/vasp-detail/VaspElectronicProperties.jsx`: accept provider-returned `image_url` while preserving existing `image_base64` API responses.
- Create `frontend/tests/periodicTableFilter.test.mjs`: element data, selection, and match semantics.
- Modify `frontend/tests/vaspTablePresentation.test.mjs`: verify wrapper/core separation and legacy compatibility.
- Modify `frontend/tests/vaspTaskDetailPresentation.test.mjs`: verify reset and dual plot-source support.

### Competition Pages

- Create `frontend/src/features/competition/components/CompetitionState.jsx`: demo banner, state/error/empty surfaces, status badge, and read-only notice.
- Create `frontend/src/features/competition/components/WorkflowTimeline.jsx`: fixed four-step dependency timeline and evidence summary.
- Create `frontend/src/features/competition/components/CompetitionTable.jsx`: shared compact workflow/result list.
- Create `frontend/src/features/competition/components/competitionComponents.css`: stable component geometry and state colors.
- Modify `frontend/src/pages/CompetitionDashboard.jsx`: operational summary, recent workflows, selected timeline, and minimal Slurm snapshot.
- Create `frontend/src/pages/competition/CompetitionNewCalculation.jsx`: four-section preview workspace with MoS2 structure and disabled writes.
- Create `frontend/src/pages/competition/CompetitionWorkflows.jsx`: searchable list and state filters.
- Create `frontend/src/pages/competition/CompetitionWorkflowDetail.jsx`: identity/provenance plus step evidence.
- Create `frontend/src/pages/competition/CompetitionResults.jsx`: success/failure result list.
- Create `frontend/src/pages/competition/CompetitionResultDetail.jsx`: final structure, BAND/DOS, properties, and demo evidence downloads.
- Create `frontend/src/pages/competition/CompetitionVaspDatabase.jsx`: periodic-table/query/filter/table/detail work surface.
- Create `frontend/src/pages/competition/CompetitionPages.css`: responsive page-level layouts at desktop, 1024px, and 390px.
- Modify `frontend/src/App107Cup.jsx`: lazy routes for the five entries and two detail routes.
- Modify `frontend/src/config/appNavigation.js`: competition-only navigation groups and page metadata.
- Modify `frontend/src/components/AppShell.jsx`: import the three new competition navigation icons and show a persistent demo marker in demo builds.
- Modify `frontend/src/components/AppShell.css`: marker and narrow-screen containment.
- Modify `frontend/tests/appNavigation107Cup.test.mjs`: exact competition routes and exclusion contract.
- Modify `frontend/tests/competitionRoles107Cup.test.mjs`: dedicated route entry and mutation-control source contract.
- Create `frontend/tests/competitionPages107Cup.test.mjs`: page composition and provenance contract.

### Browser Acceptance

- Modify `frontend/package.json` and `frontend/package-lock.json`: add `@playwright/test` and `pngjs` as dev dependencies plus `test:e2e`.
- Create `frontend/playwright.config.js`: external preview URL only, no local web server.
- Create `frontend/e2e/competition-preview.spec.js`: login, five routes, refresh, filters, 3D canvas pixels, disabled writes, console checks, and screenshots at three viewports.
- Modify `.gitignore`: exclude Playwright runtime output while preserving deliberate evidence outside the worktree.

### Independent 107 Preview

- Create `deploy/107cup/preview-build.slurm`: verify a merged `main` commit, test/build demo mode, and publish `previews/$commit` without touching `current`.
- Create `deploy/107cup/submit-preview-build.sh`: short login-node fetch/merge-commit validation and `sbatch` submission.
- Create `deploy/107cup/preview-service.slurm`: copy databases with SQLite backup into a private runtime, choose/check a separate port, and run one FastAPI process.
- Create `deploy/107cup/submit-preview-service.sh`: submit a fixed preview commit and record its Job ID.
- Create `deploy/107cup/verify-preview-runtime.sh`: short read-only job/health/manifest checks.
- Create `deploy/107cup/preview-snapshot.slurm`: Slurm-side before/after stable-state and SQLite hash/integrity evidence.
- Create `deploy/107cup/submit-preview-snapshot.sh`: submit `before|after` snapshots.
- Modify `backend/competition_runtime.py`: expose non-secret `release_kind` and `data_mode` in health metadata.
- Modify `backend/tests/test_107cup_runtime.py`: exact metadata contract.
- Create `backend/tests/test_107cup_preview_deploy_contract.py`: isolation, Slurm-only, and no-stable-mutation contracts.
- Modify `deploy/107cup/build.slurm`: explicitly set live data mode for future stable builds; no other stable-release behavior changes.
- Modify `docs/107cup/implementation-plan.md`: record this plan and later append evidence without advancing phase 5-8.

## Task 0: Enter An Isolated Implementation Worktree

**Files:** None.

- [ ] **Step 1: Merge this plan through the protected-main PR gate**

Verify the documentation PR containing this plan is merged. From the primary checkout:

```powershell
Set-Location 'D:\Documents\matflow项目\LMateLab-107Cup'
git fetch origin main
git status --short --branch
git rev-parse origin/main
```

Expected: the working tree contains no unintended changes and `origin/main` contains `docs/superpowers/plans/2026-08-10-107cup-frontend-preview.md`.

- [ ] **Step 2: Create the implementation worktree using the required skill**

Invoke `superpowers:using-git-worktrees`, then create:

```powershell
git worktree add '..\LMateLab-107Cup-frontend-preview' -b 'codex/107cup-frontend-preview' 'origin/main'
Set-Location '..\LMateLab-107Cup-frontend-preview'
git status --short --branch
```

Expected: branch is `codex/107cup-frontend-preview`, the worktree is clean, and protected `main` remains checked out only in the primary checkout.

- [ ] **Step 3: Run the baseline contracts before changing source**

```powershell
Set-Location backend
python -m unittest tests.test_107cup_authz tests.test_107cup_runtime tests.test_107cup_deploy_contract tests.test_health_readiness -v
Set-Location ..\frontend
npm test
Set-Location ..
```

Expected: the current focused backend tests and the existing frontend suite pass. Preserve any failure output and stop before implementation if the merged baseline is not green.

## Task 1: Lock The Demo And Live Data Provider Contract

**Files:**
- Create: `frontend/tests/competitionDataProvider.test.mjs`
- Create: `frontend/src/features/competition/data/competitionErrors.js`
- Create: `frontend/src/utils/elementSelection.js`
- Create: `frontend/src/features/competition/data/demoFixtures.js`
- Create: `frontend/public/competition-fixtures/mos2-band-demo.svg`
- Create: `frontend/public/competition-fixtures/mos2-dos-demo.svg`
- Create: `frontend/src/features/competition/data/demoCompetitionDataProvider.js`
- Create: `frontend/src/features/competition/data/apiCompetitionDataProvider.js`
- Create: `frontend/src/features/competition/data/competitionDataProvider.js`

- [ ] **Step 1: Write the failing provider tests**

Create tests that pin the three workflow states, fixed four-step graph, filtering, invalid mode, future live paths, and every preview mutation:

```js
import test from 'node:test';
import assert from 'node:assert/strict';

import { PreviewReadOnlyError } from '../src/features/competition/data/competitionErrors.js';
import { createDemoCompetitionDataProvider } from '../src/features/competition/data/demoCompetitionDataProvider.js';
import { createApiCompetitionDataProvider } from '../src/features/competition/data/apiCompetitionDataProvider.js';
import { createCompetitionDataProvider } from '../src/features/competition/data/competitionDataProvider.js';

test('demo fixtures expose success, running and failed MoS2 workflows', async () => {
  const provider = createDemoCompetitionDataProvider();
  const result = await provider.listWorkflows({ query: '', status: 'all' });
  assert.deepEqual(result.items.map((item) => item.status), ['succeeded', 'running', 'failed']);
  assert.deepEqual(result.items[0].steps.map((step) => step.key), ['relax', 'scf', 'band', 'dos']);
  assert.equal(result.items.every((item) => item.data_kind === 'demo'), true);
});

test('demo element mode implements at-least and exact matching', async () => {
  const provider = createDemoCompetitionDataProvider();
  assert.equal((await provider.listDatabase({ elements: ['Mo'], elementMode: 'at_least', query: '', page: 1, pageSize: 20 })).total, 3);
  assert.equal((await provider.listDatabase({ elements: ['Mo'], elementMode: 'only', query: '', page: 1, pageSize: 20 })).total, 0);
  assert.equal((await provider.listDatabase({ elements: ['Mo', 'S'], elementMode: 'only', query: '', page: 1, pageSize: 20 })).total, 3);
});

test('all demo mutations reject before fetch can run', async () => {
  let requests = 0;
  const provider = createDemoCompetitionDataProvider({ fetchImpl: async () => { requests += 1; } });
  for (const method of ['uploadStructure', 'saveDraft', 'submitWorkflow', 'cancelWorkflow', 'retryWorkflow', 'mutateDatabase']) {
    await assert.rejects(() => provider[method]({}), PreviewReadOnlyError);
  }
  assert.equal(requests, 0);
});

test('live provider uses only competition domain paths', async () => {
  const requests = [];
  const provider = createApiCompetitionDataProvider({
    authHeaders: () => ({}),
    fetchImpl: async (url, init = {}) => {
      requests.push([url, init.method || 'GET']);
      return new Response(JSON.stringify({ items: [], total: 0 }), {
        status: 200,
        headers: { 'content-type': 'application/json' },
      });
    },
  });
  await provider.getDashboard();
  await provider.listWorkflows({ query: 'MoS2', status: 'running' });
  assert.deepEqual(requests.map(([url]) => url), [
    '/api/competition/dashboard',
    '/api/competition/workflows?query=MoS2&status=running',
  ]);
});

test('live forbidden responses remain forbidden and never become demo data', async () => {
  const provider = createApiCompetitionDataProvider({
    authHeaders: () => ({}),
    fetchImpl: async () => new Response(JSON.stringify({ detail: 'viewer cannot write' }), {
      status: 403,
      headers: { 'content-type': 'application/json' },
    }),
  });
  await assert.rejects(
    () => provider.cancelWorkflow('wf-1'),
    (error) => error.status === 403 && error.code === 'forbidden' && !String(error.message).includes('demo'),
  );
});

test('demo database pagination is stable', async () => {
  const provider = createDemoCompetitionDataProvider();
  const first = await provider.listDatabase({ elements: [], elementMode: 'at_least', query: '', page: 1, pageSize: 2 });
  const second = await provider.listDatabase({ elements: [], elementMode: 'at_least', query: '', page: 2, pageSize: 2 });
  assert.equal(first.items.length, 2);
  assert.equal(second.items.length, 1);
  assert.equal(first.total, 3);
  assert.notEqual(first.items[0].id, second.items[0].id);
});

test('provider mode is fixed and invalid values fail at construction', () => {
  assert.equal(createCompetitionDataProvider('demo').mode, 'demo');
  assert.equal(createCompetitionDataProvider('live', { fetchImpl: async () => new Response('{}') }).mode, 'live');
  assert.throws(() => createCompetitionDataProvider('switchable'), /Unsupported competition data mode/);
});
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
cd frontend
node --test tests/competitionDataProvider.test.mjs
```

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `competitionErrors.js`.

- [ ] **Step 3: Add explicit error classes**

```js
export class PreviewReadOnlyError extends Error {
  constructor(action) {
    super(`预览环境不会执行${action}`);
    this.name = 'PreviewReadOnlyError';
    this.code = 'preview-read-only';
  }
}

export class CompetitionRequestError extends Error {
  constructor(message, status, code = 'request-failed') {
    super(message);
    this.name = 'CompetitionRequestError';
    this.status = status;
    this.code = status === 403 ? 'forbidden' : code;
  }
}
```

Create the shared element helper in the same RED/GREEN slice so both the demo query provider and the extracted periodic table use one definition:

```js
export function toggleElementSelection(selected, symbol) {
  return selected.includes(symbol)
    ? selected.filter((item) => item !== symbol)
    : [...selected, symbol];
}

export function matchesElementSelection(recordElements, selected, mode) {
  const record = new Set(recordElements);
  const wanted = [...new Set(selected)];
  if (wanted.length === 0) return true;
  if (!wanted.every((symbol) => record.has(symbol))) return false;
  return mode !== 'only' || record.size === wanted.length;
}
```

- [ ] **Step 4: Add the concrete MoS2 fixtures**

Use one shared structure and a helper that always emits the four fixed steps. The three records must use `wf-demo-mos2-success`, `wf-demo-mos2-running`, and `wf-demo-mos2-failed`; the failure must stop at SCF and leave BAND/DOS `blocked`, not `succeeded` with empty plots.

```js
export const DEMO_STRUCTURE = Object.freeze({
  symbols: ['Mo', 'S', 'S'],
  positions: [[0, 0, 10], [1.579, 0.912, 11.568], [1.579, 0.912, 8.432]],
  cell: [[3.158, 0, 0], [-1.579, 2.735, 0], [0, 0, 20]],
  pbc: [true, true, false],
});

const step = (key, status, jobId, overrides = {}) => Object.freeze({
  key,
  label: ({ relax: '结构优化', scf: '自洽计算', band: '能带', dos: '态密度' })[key],
  status,
  job_id: jobId,
  attempt: jobId ? 1 : null,
  attempt_dir: jobId ? `attempt-1/${key}` : null,
  slurm_state: status === 'succeeded' ? 'COMPLETED' : status === 'running' ? 'RUNNING' : status === 'failed' ? 'FAILED' : null,
  exit_code: status === 'succeeded' ? '0:0' : status === 'failed' ? '1:0' : null,
  accepted: status === 'succeeded',
  ...overrides,
});

export const DEMO_WORKFLOWS = Object.freeze([
  {
    id: 'wf-demo-mos2-success', material: 'MoS2', source: '内置单层 MoS2', status: 'succeeded', current_step: 'done', latest_job_id: 'DEMO-41004', data_kind: 'demo',
    creator: 'demo-operator', template_version: 'mos2-v1', input_sha256: 'demo-6b7340d4c85d', release_commit: 'demo-preview', updated_at: '2026-08-10T09:40:00+08:00',
    steps: [step('relax', 'succeeded', 'DEMO-41001'), step('scf', 'succeeded', 'DEMO-41002'), step('band', 'succeeded', 'DEMO-41003'), step('dos', 'succeeded', 'DEMO-41004')],
  },
  {
    id: 'wf-demo-mos2-running', material: 'MoS2', source: 'POSCAR 草稿示例', status: 'running', current_step: 'scf', latest_job_id: 'DEMO-41012', data_kind: 'demo',
    creator: 'demo-operator', template_version: 'mos2-v1', input_sha256: 'demo-73d80fe429da', release_commit: 'demo-preview', updated_at: '2026-08-10T10:05:00+08:00',
    steps: [step('relax', 'succeeded', 'DEMO-41011'), step('scf', 'running', 'DEMO-41012'), step('band', 'waiting', null), step('dos', 'waiting', null)],
  },
  {
    id: 'wf-demo-mos2-failed', material: 'MoS2', source: '人为失败算例', status: 'failed', current_step: 'scf', latest_job_id: 'DEMO-41022', data_kind: 'demo',
    creator: 'demo-operator', template_version: 'mos2-v1', input_sha256: 'demo-2f91fbbe1327', release_commit: 'demo-preview', updated_at: '2026-08-10T10:18:00+08:00',
    steps: [step('relax', 'succeeded', 'DEMO-41021'), step('scf', 'failed', 'DEMO-41022', { reason: '演示：电子步未收敛', accepted: false }), step('band', 'blocked', null), step('dos', 'blocked', null)],
  },
]);
```

Add two compact, inspectable SVG assets. Each has a white background, labelled axes, multiple scientific data lines, and a visible `DEMO` watermark. They are plot fixtures, not decorative illustrations. Keep them under Vite's `public` directory so Node provider tests do not need a non-JavaScript asset loader:

```js
const demoBandPlotUrl = '/competition-fixtures/mos2-band-demo.svg';
const demoDosPlotUrl = '/competition-fixtures/mos2-dos-demo.svg';
```

Use this complete band fixture (the DOS fixture follows the same dimensions and replaces the band polylines with a horizontal energy axis plus two filled DOS traces):

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540" role="img" aria-label="Demo MoS2 band structure">
  <rect width="960" height="540" fill="#fff"/>
  <g stroke="#d8dee8" stroke-width="1"><path d="M80 70H910M80 170H910M80 270H910M80 370H910M80 470H910"/><path d="M80 70V470M287 70V470M495 70V470M702 70V470M910 70V470"/></g>
  <g stroke="#344054" stroke-width="2"><path d="M80 70V470H910"/><path d="M80 270H910" stroke-dasharray="7 6"/></g>
  <g fill="none" stroke="#1f5fce" stroke-width="3"><polyline points="80,420 180,390 287,350 390,330 495,300 600,330 702,350 810,390 910,420"/><polyline points="80,360 180,335 287,315 390,300 495,290 600,305 702,330 810,345 910,360"/></g>
  <g fill="none" stroke="#c23b53" stroke-width="3"><polyline points="80,220 180,205 287,190 390,175 495,155 600,170 702,185 810,205 910,220"/><polyline points="80,180 180,165 287,145 390,130 495,115 600,135 702,150 810,165 910,180"/></g>
  <g fill="#475467" font-family="Arial,sans-serif" font-size="18"><text x="72" y="500">Γ</text><text x="281" y="500">M</text><text x="489" y="500">K</text><text x="696" y="500">Γ</text><text x="900" y="500">M</text><text x="410" y="528">High-symmetry path</text><text x="20" y="285" transform="rotate(-90 20 285)">Energy (eV)</text></g>
  <text x="805" y="45" fill="#b42318" font-family="Arial,sans-serif" font-size="24" font-weight="700">DEMO</text>
</svg>
```

```svg
<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540" viewBox="0 0 960 540" role="img" aria-label="Demo MoS2 density of states">
  <rect width="960" height="540" fill="#fff"/>
  <g stroke="#d8dee8" stroke-width="1"><path d="M90 70H900M90 170H900M90 270H900M90 370H900M90 470H900"/><path d="M90 70V470M292 70V470M495 70V470M697 70V470M900 70V470"/></g>
  <g stroke="#344054" stroke-width="2"><path d="M90 70V470H900"/><path d="M90 270H900" stroke-dasharray="7 6"/></g>
  <path d="M90 470C170 445 210 415 250 380C305 330 330 305 390 286C450 270 490 270 535 270C590 270 620 255 660 220C710 175 765 135 900 105L900 470Z" fill="#1f5fce" fill-opacity=".18" stroke="#1f5fce" stroke-width="3"/>
  <path d="M90 470C190 460 245 430 305 400C370 368 410 335 455 310C510 280 565 270 610 270C675 270 735 225 785 180C835 135 875 115 900 100" fill="none" stroke="#c23b53" stroke-width="3"/>
  <g fill="#475467" font-family="Arial,sans-serif" font-size="18"><text x="410" y="520">Density of states</text><text x="25" y="285" transform="rotate(-90 25 285)">Energy (eV)</text></g>
  <text x="795" y="45" fill="#b42318" font-family="Arial,sans-serif" font-size="24" font-weight="700">DEMO</text>
</svg>
```

Export the remaining fixture objects with these exact public shapes:

```js
const vaspDetail = Object.freeze({
  db: { dbname: '107 Cup Demo Database' },
  row: { id: 1, formula: 'MoS2', energy: -22.418731, fmax: 0.0062, natoms: 3, pbc: [true, true, false] },
  properties: { spacegroup: 'P-6m2', bandgap_eV: 1.78, vbm_eV: 0, cbm_eV: 1.78 },
  structure: DEMO_STRUCTURE,
  crystal: {
    lattice: { a: 3.158, b: 3.158, c: 20, alpha: 90, beta: 90, gamma: 120, volume: 172.75 },
    density_g_cm3: 0.873,
    dimensionality: 2,
    atomic_positions_frac: [
      { element: 'Mo', x: 0, y: 0, z: 0.5 },
      { element: 'S', x: 0.666667, y: 0.333333, z: 0.5784 },
      { element: 'S', x: 0.666667, y: 0.333333, z: 0.4216 },
    ],
  },
  capabilities: { structure_export: true, band_plot: true, dos_plot: true, band_data: true, dos_data: true },
});

export const DEMO_DASHBOARD = Object.freeze({
  data_kind: 'demo',
  summary: { total: 3, running: 1, recent_succeeded: 1, needs_attention: 1 },
  recent_workflows: DEMO_WORKFLOWS,
  active_workflow: DEMO_WORKFLOWS[1],
  slurm: { partition: 'P107-RTX5090', state: '演示快照', queued: 1, running: 1, updated_at: '2026-08-10T10:20:00+08:00' },
});

export const DEMO_RESULTS_BY_ID = Object.freeze({
  'wf-demo-mos2-success': {
    ...DEMO_WORKFLOWS[0],
    vasp_detail: vaspDetail,
    artifacts: ['structure-cif', 'structure-poscar', 'band-data', 'dos-data', 'evidence-bundle'],
  },
  'wf-demo-mos2-failed': {
    ...DEMO_WORKFLOWS[2],
    failure_evidence: {
      step: 'scf', job_id: 'DEMO-41022', exit_code: '1:0', reason: '演示：电子步未收敛',
      expected_files: ['OUTCAR', 'vasprun.xml'], missing_files: ['vasprun.xml'],
      log_tail: ['DEMO LOG', 'electronic minimization did not converge'],
    },
  },
});

export const DEMO_DATABASE_ROWS = Object.freeze(DEMO_WORKFLOWS.map((workflow, index) => ({
  id: `db-demo-${index + 1}`,
  _rowId: `db-demo-${index + 1}`,
  formula: 'MoS2',
  elements: ['Mo', 'S'],
  source: workflow.source,
  workflow_id: workflow.id,
  status: workflow.status,
  bandgap_eV: workflow.status === 'succeeded' ? 1.78 : null,
  energy: workflow.status === 'succeeded' ? -22.418731 : null,
  completed_at: workflow.status === 'succeeded' ? workflow.updated_at : null,
  latest_job_id: workflow.latest_job_id,
  data_kind: 'demo',
  vasp_detail: workflow.status === 'succeeded' ? vaspDetail : { ...vaspDetail, capabilities: { structure_export: false, band_plot: false, dos_plot: false, band_data: false, dos_data: false } },
})));

export const DEMO_DATABASE_METADATA = Object.freeze({
  source: { label: '来源', kind: 'text', priority: 1 },
  workflow_id: { label: '工作流', kind: 'text', priority: 1 },
  status: { label: '状态', kind: 'text', priority: 1 },
  bandgap_eV: { label: '带隙', unit: 'eV', decimals: 4, kind: 'number', priority: 1 },
  completed_at: { label: '完成时间', kind: 'text', priority: 2 },
});

export const DEMO_BAND_DATA = '# DEMO MoS2 band data\n# k_distance energy_eV\n0.0 -1.20\n0.5 -0.18\n1.0 0.00\n1.5 1.78\n';
export const DEMO_DOS_DATA = '# DEMO MoS2 DOS data\n# energy_eV dos\n-2.0 0.20\n-1.0 1.40\n0.0 0.00\n1.78 0.10\n2.5 1.20\n';
export const DEMO_POSCAR = 'DEMO MoS2\n1.0\n3.158 0 0\n-1.579 2.735 0\n0 0 20\nMo S\n1 2\nDirect\n0 0 0.5\n0.666667 0.333333 0.5784\n0.666667 0.333333 0.4216\n';
export const DEMO_CIF = 'data_DEMO_MoS2\n_cell_length_a 3.158\n_cell_length_b 3.158\n_cell_length_c 20.0\n_cell_angle_alpha 90\n_cell_angle_beta 90\n_cell_angle_gamma 120\nloop_\n_atom_site_label\n_atom_site_type_symbol\n_atom_site_fract_x\n_atom_site_fract_y\n_atom_site_fract_z\nMo1 Mo 0 0 0.5\nS1 S 0.666667 0.333333 0.5784\nS2 S 0.666667 0.333333 0.4216\n';
export const DEMO_PLOTS = Object.freeze({ band: demoBandPlotUrl, dos: demoDosPlotUrl });
```

Every object must contain or inherit `data_kind: 'demo'`. The failed result contains no successful plot capability.

- [ ] **Step 5: Implement the demo provider with no network path**

```js
const rejectMutation = (label) => async () => { throw new PreviewReadOnlyError(label); };

export function createDemoCompetitionDataProvider() {
  return Object.freeze({
    mode: 'demo',
    readOnly: true,
    getDashboard: async () => structuredClone(DEMO_DASHBOARD),
    listWorkflows: async ({ query = '', status = 'all' } = {}) => {
      const needle = query.trim().toLowerCase();
      const items = DEMO_WORKFLOWS.filter((item) => (
        (status === 'all' || item.status === status)
        && (!needle || `${item.id} ${item.material} ${item.source}`.toLowerCase().includes(needle))
      ));
      return { items: structuredClone(items), total: items.length, data_kind: 'demo' };
    },
    getWorkflow: async (id) => structuredClone(DEMO_WORKFLOWS.find((item) => item.id === id) || null),
    listResults: async (filters = {}) => listDemoResults(filters),
    getResult: async (id) => structuredClone(DEMO_RESULTS_BY_ID[id] || null),
    listDatabase: async (filters = {}) => listDemoDatabase(filters),
    getDatabaseRecord: async (id) => structuredClone(DEMO_DATABASE_ROWS.find((item) => item.id === id) || null),
    loadPlot: async (workflowId, kind) => loadDemoPlot(workflowId, kind),
    downloadArtifact: async (workflowId, kind) => downloadDemoArtifact(workflowId, kind),
    uploadStructure: rejectMutation('结构上传'),
    saveDraft: rejectMutation('草稿保存'),
    submitWorkflow: rejectMutation('工作流提交'),
    cancelWorkflow: rejectMutation('工作流取消'),
    retryWorkflow: rejectMutation('工作流重试'),
    mutateDatabase: rejectMutation('数据库写入'),
  });
}
```

Implement the referenced helpers concretely:

```js
function listDemoResults({ query = '', status = 'all' } = {}) {
  const needle = query.trim().toLowerCase();
  const items = Object.values(DEMO_RESULTS_BY_ID).filter((item) => (
    (status === 'all' || item.status === status)
    && (!needle || `${item.id} ${item.material} ${item.source}`.toLowerCase().includes(needle))
  ));
  return Promise.resolve({ items: structuredClone(items), total: items.length, data_kind: 'demo' });
}

function listDemoDatabase({ query = '', elements = [], elementMode = 'at_least', page = 1, pageSize = 20 } = {}) {
  const needle = query.trim().toLowerCase();
  const filtered = DEMO_DATABASE_ROWS.filter((item) => (
    matchesElementSelection(item.elements, elements, elementMode)
    && (!needle || `${item.formula} ${item.source} ${item.workflow_id}`.toLowerCase().includes(needle))
  ));
  const start = (Math.max(1, page) - 1) * pageSize;
  return Promise.resolve({
    items: structuredClone(filtered.slice(start, start + pageSize)),
    total: filtered.length,
    available_elements: ['Mo', 'S'],
    metadata: DEMO_DATABASE_METADATA,
    data_kind: 'demo',
  });
}

function loadDemoPlot(workflowId, kind) {
  if (workflowId !== 'wf-demo-mos2-success' || !DEMO_PLOTS[kind]) throw new CompetitionRequestError('该演示结果没有可验收图像', 404, 'parse-error');
  return Promise.resolve({ image_url: DEMO_PLOTS[kind], data_kind: 'demo' });
}

function downloadDemoArtifact(workflowId, kind) {
  if (workflowId !== 'wf-demo-mos2-success') throw new CompetitionRequestError('该演示结果没有可下载产物', 404);
  const payloads = {
    'band-data': ['DEMO-band.dat', DEMO_BAND_DATA, 'text/plain'],
    'dos-data': ['DEMO-dos.dat', DEMO_DOS_DATA, 'text/plain'],
    'structure-cif': ['DEMO-MoS2.cif', DEMO_CIF, 'text/plain'],
    'structure-poscar': ['DEMO-POSCAR', DEMO_POSCAR, 'text/plain'],
    'evidence-bundle': ['DEMO-evidence.json', JSON.stringify(DEMO_RESULTS_BY_ID[workflowId], null, 2), 'application/json'],
  };
  const item = payloads[kind];
  if (!item) throw new CompetitionRequestError(`未知演示产物: ${kind}`, 404);
  return Promise.resolve({ filename: item[0], blob: new Blob([item[1]], { type: item[2] }), data_kind: 'demo' });
}
```

Define `DEMO_CIF` and `DEMO_POSCAR` beside the BAND/DOS text fixtures, each beginning with a `DEMO` comment/title and containing the same three-atom structure.

- [ ] **Step 6: Implement the live API provider without fallback**

Implement one internal `requestJson(path, init)` that attaches `getAuthHeaders()`, parses JSON, throws `CompetitionRequestError` with HTTP status, and never imports `demoFixtures.js`. Use these exact paths:

```js
getDashboard()                         -> GET  /api/competition/dashboard
listWorkflows(filters)                 -> GET  /api/competition/workflows (URLSearchParams: query, status)
getWorkflow(id)                        -> GET  /api/competition/workflows/{id}
listResults(filters)                   -> GET  /api/competition/results (URLSearchParams: query, status)
getResult(id)                          -> GET  /api/competition/results/{id}
listDatabase(filters)                  -> GET  /api/competition/vasp/records (URLSearchParams: query, elements, element_mode, page, page_size)
getDatabaseRecord(id)                  -> GET  /api/competition/vasp/records/{id}
loadPlot(id, kind)                     -> GET  /api/competition/results/{id}/{band|dos}-plot
downloadArtifact(id, kind)             -> GET  /api/competition/results/{id}/artifacts/{kind}
uploadStructure(file)                  -> POST /api/competition/structures
saveDraft(payload)                     -> POST /api/competition/drafts
submitWorkflow(id)                     -> POST /api/competition/workflows/{id}/submit
cancelWorkflow(id)                     -> POST /api/competition/workflows/{id}/cancel
retryWorkflow({ id, step })            -> POST /api/competition/workflows/{id}/steps/{step}/retry
```

The implementation must return backend failures unchanged as errors. A `404`, `403`, stale marker, or parse failure must never call the demo provider.

Use one complete provider object; `jsonPost` stringifies JSON, while `uploadStructure` uses `FormData` without forcing a JSON content type:

```js
export function createApiCompetitionDataProvider({ fetchImpl = fetch, authHeaders = getAuthHeaders } = {}) {
  async function request(path, init = {}) {
    const form = typeof FormData !== 'undefined' && init.body instanceof FormData;
    const response = await fetchImpl(path, {
      ...init,
      headers: { ...authHeaders(form ? null : 'application/json'), ...(init.headers || {}) },
    });
    if (!response.ok) {
      const contentType = response.headers.get('content-type') || '';
      const body = contentType.includes('application/json') ? await response.json() : await response.text();
      const detail = typeof body?.detail === 'string' ? body.detail : String(body?.detail || body || `HTTP ${response.status}`);
      throw new CompetitionRequestError(detail, response.status);
    }
    return response;
  }
  const json = async (path, init) => (await request(path, init)).json();
  const jsonPost = (path, body) => json(path, { method: 'POST', body: JSON.stringify(body) });
  const query = (values) => {
    const params = new URLSearchParams();
    Object.entries(values).forEach(([key, value]) => {
      if (value !== '' && value !== undefined && value !== null && value !== 'all') params.set(key, Array.isArray(value) ? value.join(',') : String(value));
    });
    const text = params.toString();
    return text ? `?${text}` : '';
  };
  return Object.freeze({
    mode: 'live',
    readOnly: false,
    getDashboard: () => json('/api/competition/dashboard'),
    listWorkflows: (filters = {}) => json(`/api/competition/workflows${query(filters)}`),
    getWorkflow: (id) => json(`/api/competition/workflows/${encodeURIComponent(id)}`),
    listResults: (filters = {}) => json(`/api/competition/results${query(filters)}`),
    getResult: (id) => json(`/api/competition/results/${encodeURIComponent(id)}`),
    listDatabase: (filters = {}) => json(`/api/competition/vasp/records${query({
      query: filters.query,
      elements: filters.elements,
      element_mode: filters.elementMode,
      page: filters.page,
      page_size: filters.pageSize,
    })}`),
    getDatabaseRecord: (id) => json(`/api/competition/vasp/records/${encodeURIComponent(id)}`),
    loadPlot: (id, kind) => json(`/api/competition/results/${encodeURIComponent(id)}/${kind}-plot`),
    downloadArtifact: async (id, kind) => {
      const response = await request(`/api/competition/results/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(kind)}`);
      const disposition = response.headers.get('content-disposition') || '';
      const filename = /filename="?([^";]+)"?/i.exec(disposition)?.[1] || `${id}-${kind}`;
      return { filename, blob: await response.blob(), data_kind: 'live' };
    },
    uploadStructure: async (file) => {
      const body = new FormData();
      body.append('file', file);
      return json('/api/competition/structures', { method: 'POST', body });
    },
    saveDraft: (payload) => jsonPost('/api/competition/drafts', payload),
    submitWorkflow: (id) => jsonPost(`/api/competition/workflows/${encodeURIComponent(id)}/submit`, {}),
    cancelWorkflow: (id) => jsonPost(`/api/competition/workflows/${encodeURIComponent(id)}/cancel`, {}),
    retryWorkflow: ({ id, step }) => jsonPost(`/api/competition/workflows/${encodeURIComponent(id)}/steps/${encodeURIComponent(step)}/retry`, {}),
    mutateDatabase: (payload) => jsonPost('/api/competition/vasp/records', payload),
  });
}
```

- [ ] **Step 7: Add build-time provider selection and rerun tests**

```js
export function createCompetitionDataProvider(mode, options = {}) {
  if (mode === 'demo') return createDemoCompetitionDataProvider(options);
  if (mode === 'live') return createApiCompetitionDataProvider(options);
  throw new Error(`Unsupported competition data mode: ${mode}`);
}

const viteEnv = typeof import.meta.env === 'object' ? import.meta.env : {};
export const competitionDataMode = viteEnv.VITE_COMPETITION_DATA_MODE || 'live';
export const competitionDataProvider = createCompetitionDataProvider(competitionDataMode);
```

Run:

```bash
cd frontend
node --test tests/competitionDataProvider.test.mjs
npm test
```

Expected: provider tests PASS; the full existing frontend suite remains green.

- [ ] **Step 8: Commit the data boundary**

```bash
git add frontend/src/features/competition/data frontend/public/competition-fixtures frontend/src/utils/elementSelection.js frontend/tests/competitionDataProvider.test.mjs
git commit -m "feat(107cup): add preview data providers"
```

## Task 2: Extract The Reusable 118-Element Periodic Table

**Files:**
- Create: `frontend/src/pages/db/periodicTableElements.js`
- Create: `frontend/src/pages/db/PeriodicTableFilter.jsx`
- Create: `frontend/src/pages/db/PeriodicTableFilter.css`
- Create: `frontend/tests/periodicTableFilter.test.mjs`
- Modify: `frontend/src/pages/db/PersonalVaspDatabase.jsx`

- [ ] **Step 1: Write failing pure-contract tests**

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { PERIODIC_TABLE_ELEMENTS } from '../src/pages/db/periodicTableElements.js';
import { matchesElementSelection, toggleElementSelection } from '../src/utils/elementSelection.js';

test('periodic table contains each atomic number exactly once', () => {
  assert.equal(PERIODIC_TABLE_ELEMENTS.length, 118);
  assert.deepEqual(PERIODIC_TABLE_ELEMENTS.map((item) => item.Z), Array.from({ length: 118 }, (_, index) => index + 1));
  assert.deepEqual(PERIODIC_TABLE_ELEMENTS.find((item) => item.symbol === 'Mo'), { Z: 42, symbol: 'Mo', name: 'Molybdenum', row: 5, col: 6 });
});

test('selection toggles without duplicates', () => {
  assert.deepEqual(toggleElementSelection(['Mo'], 'S'), ['Mo', 'S']);
  assert.deepEqual(toggleElementSelection(['Mo', 'S'], 'Mo'), ['S']);
});

test('element matching distinguishes at-least from only', () => {
  assert.equal(matchesElementSelection(['Mo', 'S'], ['Mo'], 'at_least'), true);
  assert.equal(matchesElementSelection(['Mo', 'S'], ['Mo'], 'only'), false);
  assert.equal(matchesElementSelection(['Mo', 'S'], ['S', 'Mo'], 'only'), true);
});
```

- [ ] **Step 2: Run the test and verify RED**

Run `cd frontend && node --test tests/periodicTableFilter.test.mjs`.

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `periodicTableElements.js`.

- [ ] **Step 3: Move the exact legacy element data without retyping it**

Move the complete existing `ELEMENTS` array block currently beginning at `PersonalVaspDatabase.jsx:22` through its closing bracket into `periodicTableElements.js`. Change only its declaration from `const ELEMENTS = [` to `export const PERIODIC_TABLE_ELEMENTS = Object.freeze([` and its final `];` to `]);`; all 118 object literals remain byte-for-byte unchanged.

This is a mechanical extraction: the resulting array must deep-equal the pre-extraction array and the test above must prove the length, ordering, and Mo position. Do not source a second periodic table package or truncate lanthanides/actinides.

- [ ] **Step 4: Implement the controlled filter and pure helpers**

```jsx
import { matchesElementSelection, toggleElementSelection } from '../../utils/elementSelection';

export { matchesElementSelection, toggleElementSelection };

export default function PeriodicTableFilter({
  availableElements,
  selectedElements,
  mode,
  onSelectionChange,
  onModeChange,
}) {
  const available = new Set(availableElements);
  return (
    <section className="vasp-periodic-filter" aria-label="元素周期表筛选">
      <div className="vasp-periodic-toolbar">
        <div className="vasp-segmented-control" aria-label="元素匹配模式">
          <button type="button" className={mode === 'at_least' ? 'is-active' : ''} onClick={() => onModeChange('at_least')}>至少含有所选元素</button>
          <button type="button" className={mode === 'only' ? 'is-active' : ''} onClick={() => onModeChange('only')}>只含所选元素</button>
        </div>
        <button type="button" onClick={() => onSelectionChange([])} disabled={selectedElements.length === 0}>清空选择</button>
      </div>
      <div className="vasp-selected-elements" aria-live="polite">
        {selectedElements.length === 0 ? <span>未选择元素</span> : selectedElements.map((symbol) => (
          <button key={symbol} type="button" onClick={() => onSelectionChange(toggleElementSelection(selectedElements, symbol))} title={`移除 ${symbol}`}>{symbol}</button>
        ))}
      </div>
      <div className="vasp-periodic-scroll">
        <div className="vasp-periodic-grid">
          {PERIODIC_TABLE_ELEMENTS.map((element) => {
            const present = available.has(element.symbol);
            const selected = selectedElements.includes(element.symbol);
            return (
              <button
                key={element.Z}
                type="button"
                className={`vasp-element-cell${present ? ' is-present' : ''}${selected ? ' is-selected' : ''}`}
                style={{ gridColumn: element.col, gridRow: element.row }}
                aria-pressed={selected}
                onClick={() => onSelectionChange(toggleElementSelection(selectedElements, element.symbol))}
                title={`${element.name} (${element.symbol}, Z=${element.Z})`}
              >
                <small>{element.Z}</small><strong>{element.symbol}</strong>
              </button>
            );
          })}
        </div>
      </div>
    </section>
  );
}
```

CSS requirements are concrete: `--element-cell: 42px`, `grid-template-columns: repeat(18, var(--element-cell))`, `grid-auto-rows: var(--element-cell)`, `min-width: max-content`, `overflow-x: auto`, card radius no greater than `7px`, and selected/present/absent states must remain visually distinct.

- [ ] **Step 5: Replace the legacy inline periodic-table renderer**

Import `PeriodicTableFilter` and replace the inline toolbar/grid with:

```jsx
<PeriodicTableFilter
  availableElements={[...highlightElemsSet]}
  selectedElements={selectedElems}
  mode={elemMode}
  onSelectionChange={(next) => { setTasksPage(1); setSelectedElems(next); }}
  onModeChange={(next) => { setTasksPage(1); setElemMode(next); }}
/>
```

Remove the extracted `ELEMENTS`, `cellSize`, `tableWrapRef`, `gridStyle`, `cellBase`, and `renderElementCell`. Do not change `selectedElems`, `elemMode`, query-string serialization, element-fetch endpoints, upload, favorite, or custom-database behavior.

- [ ] **Step 6: Run focused and legacy tests**

```bash
cd frontend
node --test tests/periodicTableFilter.test.mjs tests/vaspTablePresentation.test.mjs
npm test
```

Expected: all tests PASS and the legacy source no longer defines `const ELEMENTS` or an inline `renderElementCell`.

- [ ] **Step 7: Commit the periodic table extraction**

```bash
git add frontend/src/pages/db/periodicTableElements.js frontend/src/pages/db/PeriodicTableFilter.jsx frontend/src/pages/db/PeriodicTableFilter.css frontend/src/pages/db/PersonalVaspDatabase.jsx frontend/tests/periodicTableFilter.test.mjs
git commit -m "refactor(vasp): extract periodic table filter"
```

## Task 3: Extract A Read-Only VASP Record Table

**Files:**
- Create: `frontend/src/pages/db/VaspRecordTable.jsx`
- Modify: `frontend/src/pages/db/VaspDataTable.jsx`
- Modify: `frontend/src/pages/db/VaspDataTable.css`
- Modify: `frontend/tests/vaspTablePresentation.test.mjs`

- [ ] **Step 1: Add a failing compatibility test**

Append:

```js
test('read-only table core is separate from legacy mutations', () => {
  const core = readFileSync(new URL('../src/pages/db/VaspRecordTable.jsx', import.meta.url), 'utf8');
  const wrapper = readFileSync(new URL('../src/pages/db/VaspDataTable.jsx', import.meta.url), 'utf8');
  assert.doesNotMatch(core, /收藏|移除|onCollect|onRemove|customDbs/);
  assert.match(core, /detailPathForItem/);
  assert.match(core, /mobileMode/);
  assert.match(core, /is-mobile-scroll/);
  assert.match(wrapper, /VaspRecordTable/);
  assert.match(wrapper, /RowActions/);
});
```

- [ ] **Step 2: Run the test and verify RED**

Run `cd frontend && node --test tests/vaspTablePresentation.test.mjs`.

Expected: FAIL because `VaspRecordTable.jsx` does not exist.

- [ ] **Step 3: Move rendering into a read-only core**

The new component owns `IdValue`, `Value`, the desktop table, mobile records, loading/empty states, and uses the existing `formatVaspValue`/`getVaspColumnPresentation`. Its public contract is:

```jsx
export default function VaspRecordTable({
  records,
  columns,
  metadata,
  loading = false,
  loadedOnce = true,
  detailPathForItem,
  onSelect = null,
  renderCell = null,
  mobileMode = 'cards',
  renderActions = null,
})
```

`IdValue` must call `detailPathForItem(item)` and render plain text when it returns an empty value. `renderCell(column, item)` may return a domain-specific React node such as a status badge; `undefined` selects the existing VASP formatter. When `onSelect` is provided, desktop rows and mobile records invoke it on click and on `Enter`, receive `tabIndex=0`, and use an accessible label derived from formula/ID; legacy rows omit this behavior. Add the action `<th>` and action cells only when `renderActions` is a function; set `columnCount = columns.length + (renderActions ? 1 : 0)`. Preserve both responsive markups and add `is-mobile-scroll` when `mobileMode === 'scroll'`; its mobile CSS keeps `.vasp-table-scroll` visible with local horizontal overflow and hides `.vasp-mobile-records`. The default `cards` mode preserves the legacy page.

- [ ] **Step 4: Reduce `VaspDataTable` to a compatibility wrapper**

```jsx
export default function VaspDataTable(props) {
  const renderActions = (item) => (
    <RowActions
      item={item}
      customDbs={props.customDbs}
      dbScope={props.dbScope}
      removingRowId={props.removingRowId}
      onOpenParams={props.onOpenParams}
      onCollect={props.onCollect}
      onRemove={props.onRemove}
    />
  );
  return (
    <VaspRecordTable
      records={props.tasks}
      columns={props.columns}
      metadata={props.metadata}
      loading={props.loading}
      loadedOnce={props.loadedOnce}
      detailPathForItem={(item) => item?._dbKey && item?._rowId
        ? `/dashboard/db/vasp/task/${encodeURIComponent(item._dbKey)}/${encodeURIComponent(String(item._rowId))}`
        : ''}
      renderActions={renderActions}
    />
  );
}
```

- [ ] **Step 5: Run focused and full tests**

```bash
cd frontend
node --test tests/vaspTablePresentation.test.mjs
npm test
```

Expected: all tests PASS; legacy table actions and task-detail links remain present only in the wrapper.

- [ ] **Step 6: Commit the table extraction**

```bash
git add frontend/src/pages/db/VaspRecordTable.jsx frontend/src/pages/db/VaspDataTable.jsx frontend/src/pages/db/VaspDataTable.css frontend/tests/vaspTablePresentation.test.mjs
git commit -m "refactor(vasp): extract read-only record table"
```

## Task 4: Add Competition Provider Context And Navigation Data

**Files:**
- Create: `frontend/src/features/competition/CompetitionDataContext.jsx`
- Modify: `frontend/src/config/appNavigation.js`
- Modify: `frontend/src/App107Cup.jsx`
- Modify: `frontend/tests/appNavigation107Cup.test.mjs`
- Modify: `frontend/tests/competitionRoles107Cup.test.mjs`

- [ ] **Step 1: Change navigation tests to the five-entry contract**

```js
test('107 cup edition exposes only the focused competition route', () => {
  const groups = navigation.navigationGroupsForEdition('107cup');
  assert.deepEqual(groups.flatMap((group) => group.items.map((item) => [item.key, item.path])), [
    ['dashboard', '/dashboard'],
    ['competition-new', '/dashboard/calculations/new'],
    ['competition-workflows', '/dashboard/workflows'],
    ['competition-results', '/dashboard/results'],
    ['competition-vasp-db', '/dashboard/database/vasp'],
  ]);
});
```

Keep route-source assertions unchanged in this task; the seven protected routes are added atomically in Task 10 after all lazy page modules exist.

- [ ] **Step 2: Run the navigation test and verify RED**

```bash
cd frontend
node --test tests/appNavigation107Cup.test.mjs
```

Expected: FAIL because only `dashboard` is currently exposed.

- [ ] **Step 3: Add a fixed competition navigation definition**

Do not add competition items to `fullNavigationGroups`. Return a separate immutable group for the 107 edition:

```js
const competitionNavigationGroups = [{
  key: 'competition',
  label: 'VASP 计算闭环',
  items: [
    { key: 'dashboard', label: '工作台', path: '/dashboard', icon: 'LayoutDashboard', exact: true, description: '竞赛工作流与资源概览' },
    { key: 'competition-new', label: '新建计算', path: '/dashboard/calculations/new', icon: 'SquarePlus', exact: true, description: '配置固定四步 VASP 工作流' },
    { key: 'competition-workflows', label: '工作流', path: '/dashboard/workflows', icon: 'Workflow', activePrefixes: ['/dashboard/workflows/'], description: '查看步骤、作业与失败证据' },
    { key: 'competition-results', label: '结果', path: '/dashboard/results', icon: 'ChartNoAxesCombined', activePrefixes: ['/dashboard/results/'], description: '查看结构、BAND 与 DOS' },
    { key: 'competition-vasp-db', label: 'VASP 数据库', path: '/dashboard/database/vasp', icon: 'Database', exact: true, description: '按元素检索竞赛结果' },
  ],
}];

export function navigationGroupsForEdition(edition = '') {
  return edition === '107cup' ? competitionNavigationGroups : fullNavigationGroups;
}
```

- [ ] **Step 4: Add the provider context and query hook**

```jsx
const CompetitionDataContext = createContext(null);

export function CompetitionDataProvider({ children, provider = competitionDataProvider }) {
  const value = useMemo(() => ({ provider, mode: provider.mode, readOnly: provider.readOnly }), [provider]);
  return <CompetitionDataContext.Provider value={value}>{children}</CompetitionDataContext.Provider>;
}

export function useCompetitionData() {
  const value = useContext(CompetitionDataContext);
  if (!value) throw new Error('useCompetitionData must be used inside CompetitionDataProvider');
  return value;
}

export function useCompetitionResource(loader) {
  const [state, setState] = useState({ status: 'loading', data: null, error: null });
  useEffect(() => {
    let active = true;
    setState({ status: 'loading', data: null, error: null });
    loader().then((data) => {
      if (active) setState({ status: data == null ? 'empty' : 'ready', data, error: null });
    }).catch((error) => {
      if (active) setState({ status: error?.code === 'forbidden' ? 'forbidden' : 'error', data: null, error });
    });
    return () => { active = false; };
  }, [loader]);
  return state;
}
```

Every page must wrap its loader in `useCallback` with the provider and serialized filters as dependencies. Do not pass a new inline function on each render.

- [ ] **Step 5: Wrap the existing protected dashboard in the provider**

Keep the single existing dashboard route in this task, but change its shell to:

```jsx
function ProtectedAppShell() {
  return (
    <RequireAuth>
      <CompetitionDataProvider>
        <AppShell />
      </CompetitionDataProvider>
    </RequireAuth>
  );
}
```

Add `assert.match(competitionApp, /CompetitionDataProvider/)` to `competitionRoles107Cup.test.mjs`. Do not add the remaining routes until Task 10.

- [ ] **Step 6: Rerun the navigation, provider, and shell tests**

```bash
cd frontend
node --test tests/appNavigation107Cup.test.mjs tests/competitionDataProvider.test.mjs tests/competitionRoles107Cup.test.mjs
```

Expected: both tests PASS. `App107Cup.jsx` still points only to its existing buildable dashboard route until Task 10.

- [ ] **Step 7: Commit navigation data and provider context**

```bash
git add frontend/src/features/competition/CompetitionDataContext.jsx frontend/src/config/appNavigation.js frontend/src/App107Cup.jsx frontend/tests/appNavigation107Cup.test.mjs frontend/tests/competitionRoles107Cup.test.mjs
git commit -m "feat(107cup): add preview navigation data"
```

## Task 5: Build Shared Competition State And Scientific Adapters

**Files:**
- Create: `frontend/src/features/competition/components/CompetitionState.jsx`
- Create: `frontend/src/features/competition/components/WorkflowTimeline.jsx`
- Create: `frontend/src/features/competition/components/CompetitionTable.jsx`
- Create: `frontend/src/features/competition/components/competitionComponents.css`
- Modify: `frontend/src/pages/db/vasp-detail/VaspStructureViewer.jsx`
- Modify: `frontend/src/pages/db/vasp-detail/VaspElectronicProperties.jsx`
- Modify: `frontend/tests/vaspTaskDetailPresentation.test.mjs`
- Create: `frontend/tests/competitionPages107Cup.test.mjs`

- [ ] **Step 1: Write failing shared-component source contracts**

```js
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const read = (path) => readFileSync(new URL(path, import.meta.url), 'utf8');

test('competition state surfaces keep demo and failure states explicit', () => {
  const source = read('../src/features/competition/components/CompetitionState.jsx');
  assert.match(source, /演示数据/);
  assert.match(source, /loading|正在加载/);
  assert.match(source, /empty|暂无/);
  assert.match(source, /forbidden|权限不足/);
  assert.match(source, /stale|最后可信状态/);
  assert.match(source, /parse-error|解析失败/);
});

test('workflow timeline is fixed to relax scf band dos and keeps job evidence', () => {
  const source = read('../src/features/competition/components/WorkflowTimeline.jsx');
  for (const token of ['relax', 'scf', 'band', 'dos', 'job_id', 'exit_code', 'attempt_dir']) assert.match(source, new RegExp(token));
});
```

Extend `vaspTaskDetailPresentation.test.mjs`:

```js
test('structure viewer exposes reset and electronic plots accept provider URLs', () => {
  const viewer = read('../src/pages/db/vasp-detail/VaspStructureViewer.jsx');
  const electronic = read('../src/pages/db/vasp-detail/VaspElectronicProperties.jsx');
  assert.match(viewer, /RotateCcw/);
  assert.match(viewer, /viewerRef/);
  assert.match(viewer, /重置结构视角/);
  assert.match(electronic, /image_url/);
  assert.match(electronic, /image_base64/);
});
```

- [ ] **Step 2: Run the tests and verify RED**

```bash
cd frontend
node --test tests/competitionPages107Cup.test.mjs tests/vaspTaskDetailPresentation.test.mjs
```

Expected: FAIL because competition shared components and reset support do not exist.

- [ ] **Step 3: Implement explicit page state components**

`CompetitionState.jsx` must export:

```jsx
export function DemoDataBanner() {
  return <div className="competition-demo-banner" role="status"><FlaskConical size={15} />演示数据：不会写入数据库或提交 Slurm 作业</div>;
}

export function CompetitionState({ status, message }) {
  if (status === 'loading') return <div className="competition-state is-loading">正在加载...</div>;
  if (status === 'empty') return <div className="competition-state">暂无匹配记录</div>;
  if (status === 'stale') return <div className="competition-state is-stale">状态陈旧：{message || '显示最后可信状态和更新时间'}</div>;
  if (status === 'forbidden') return <div className="competition-state is-error">权限不足：{message || '当前身份不能读取此数据'}</div>;
  if (status === 'parse-error') return <div className="competition-state is-error">解析失败：{message || '未生成可验收结果'}</div>;
  if (status === 'render-error') return <div className="competition-state is-error">渲染失败：{message || '请查看原始数据'}</div>;
  if (status === 'error') return <div className="competition-state is-error">加载失败：{message || '服务暂时不可用'}</div>;
  return null;
}

export function StatusBadge({ status }) {
  const labels = { succeeded: '已验收', running: '运行中', waiting: '等待', blocked: '已阻断', failed: '失败', stale: '状态陈旧' };
  return <span className={`competition-status is-${status}`}>{labels[status] || status}</span>;
}

export function PreviewReadOnlyNotice() {
  return <p className="competition-readonly-notice">预览环境不会写入或提交</p>;
}
```

All state containers use a stable minimum height of `96px`; status badges use fixed line height and no negative letter spacing.

- [ ] **Step 4: Implement the fixed workflow timeline**

```jsx
const REQUIRED_STEPS = ['relax', 'scf', 'band', 'dos'];

export default function WorkflowTimeline({ steps = [], compact = false }) {
  const byKey = new Map(steps.map((step) => [step.key, step]));
  return (
    <ol className={`competition-timeline${compact ? ' is-compact' : ''}`} aria-label="固定四步 VASP 工作流">
      {REQUIRED_STEPS.map((key) => {
        const step = byKey.get(key) || { key, status: 'waiting', label: key.toUpperCase() };
        return (
          <li key={key} className={`is-${step.status}`}>
            <div className="competition-timeline-heading"><strong>{step.label || key.toUpperCase()}</strong><StatusBadge status={step.status} /></div>
            {!compact ? (
              <dl>
                <div><dt>Job ID</dt><dd>{step.job_id || '-'}</dd></div>
                <div><dt>Attempt</dt><dd>{step.attempt ?? '-'}</dd></div>
                <div><dt>目录</dt><dd>{step.attempt_dir || '-'}</dd></div>
                <div><dt>Slurm</dt><dd>{step.slurm_state || '-'} / {step.exit_code || '-'}</dd></div>
                {step.reason ? <div><dt>结论</dt><dd>{step.reason}</dd></div> : null}
              </dl>
            ) : null}
          </li>
        );
      })}
    </ol>
  );
}
```

The CSS must show dependency connectors, but BAND and DOS both visually originate after SCF; the UI must not claim DOS depends on BAND.

- [ ] **Step 5: Implement one shared compact list**

`CompetitionTable` accepts `items`, `kind`, and `onOpen`. It renders material, source, status, current step, latest Job ID, updated time, and one icon-only `ArrowRight` action with title/aria-label. On mobile, the table remains inside `.competition-table-scroll` with `overflow-x: auto`; do not switch to decorative nested cards.

- [ ] **Step 6: Add reset support without replacing the existing 3Dmol viewer**

Import `RotateCcw`, store the created viewer in `viewerRef.current`, clear it on cleanup, and add:

```jsx
<button
  className="vasp-viewer-reset"
  type="button"
  onClick={() => { viewerRef.current?.zoomTo(); viewerRef.current?.render(); }}
  title="重置结构视角"
  aria-label="重置结构视角"
>
  <RotateCcw size={16} />
</button>
```

Do not change element coloring, axes, orthographic projection, resize observer, or cleanup.

- [ ] **Step 7: Accept plot URLs while preserving the existing base64 contract**

Replace only the image-state assignment and render source:

```js
const imageSource = data?.image_url || (data?.image_base64 ? `data:image/png;base64,${data.image_base64}` : '');
setPlotCache((current) => ({ ...current, [activeTab]: imageSource }));
```

```jsx
{activeImage ? <img src={activeImage} alt={plotAlt} /> : null}
```

Existing real API responses using `image_base64` remain unchanged. Demo fixture assets use version-controlled URLs.

- [ ] **Step 8: Run tests and commit shared UI**

```bash
cd frontend
node --test tests/competitionPages107Cup.test.mjs tests/vaspTaskDetailPresentation.test.mjs
npm test
git add src/features/competition/components src/pages/db/vasp-detail/VaspStructureViewer.jsx src/pages/db/vasp-detail/VaspElectronicProperties.jsx tests/competitionPages107Cup.test.mjs tests/vaspTaskDetailPresentation.test.mjs
git commit -m "feat(107cup): add workflow presentation components"
```

Expected: all frontend tests PASS.

## Task 6: Replace The Minimal Dashboard With An Operational Preview

**Files:**
- Modify: `frontend/src/pages/CompetitionDashboard.jsx`
- Modify: `frontend/src/pages/Dashboard.css`
- Modify: `frontend/tests/competitionPages107Cup.test.mjs`

- [ ] **Step 1: Add a failing dashboard composition test**

```js
test('competition dashboard shows operational summary and no static zero database claim', () => {
  const source = read('../src/pages/CompetitionDashboard.jsx');
  for (const token of ['getDashboard', '新建计算', '最近工作流', 'WorkflowTimeline', 'Slurm 资源', 'DemoDataBanner']) assert.match(source, new RegExp(token));
  assert.doesNotMatch(source, />0<|暂无工作流记录/);
});
```

- [ ] **Step 2: Run the test and verify RED**

Run `cd frontend && node --test tests/competitionPages107Cup.test.mjs`.

Expected: FAIL because the current dashboard contains a hard-coded zero and empty workflow panel.

- [ ] **Step 3: Load dashboard data through context**

Add `import './Dashboard.css';` directly in `CompetitionDashboard.jsx`; after Task 10 it is no longer loaded indirectly through the standard `Dashboard.jsx` module.

```jsx
const { provider, mode } = useCompetitionData();
const loadDashboard = useCallback(() => provider.getDashboard(), [provider]);
const state = useCompetitionResource(loadDashboard);
if (state.status !== 'ready') return <main className="competition-page"><DemoDataBanner /><CompetitionState status={state.status} message={state.error?.message} /></main>;
const { summary, recent_workflows, active_workflow, slurm } = state.data;
```

- [ ] **Step 4: Render the complete operational dashboard**

The page must contain, in this order:

1. Persistent `DemoDataBanner` when `mode === 'demo'`.
2. Header `107 杯 VASP 计算工作台`, supporting copy `结构到 BAND/DOS 的固定可追溯闭环`, and a `SquarePlus` command linking to `/dashboard/calculations/new`.
3. Four stable summary cells: total, running, recently succeeded, needs attention.
4. Main band with `CompetitionTable` for recent workflows.
5. Side band with compact `WorkflowTimeline` for the current workflow.
6. Minimal Slurm summary showing partition, queue state, last update, and `演示快照`; it must not list unrelated usernames, job names, or work directories.

Use `Link` for navigation and preserve the current work-focused visual language. Do not show `正常运行` as a live claim when provider mode is demo.

- [ ] **Step 5: Add dashboard-specific responsive CSS**

At desktop use `grid-template-columns: minmax(0, 1.65fr) minmax(280px, .85fr)`. At `max-width: 1120px`, stack the timeline below the table. At `max-width: 700px`, keep two summary columns and make the primary action a 36px icon button with an accessible label.

- [ ] **Step 6: Run tests and commit**

```bash
cd frontend
node --test tests/competitionPages107Cup.test.mjs
VITE_LMATELAB_EDITION=107cup VITE_COMPETITION_DATA_MODE=demo npm run build
git add src/pages/CompetitionDashboard.jsx src/pages/Dashboard.css tests/competitionPages107Cup.test.mjs
git commit -m "feat(107cup): build competition dashboard preview"
```

Expected: test and Vite build PASS once route integration has landed; if route integration is intentionally deferred to Task 10, import this page directly in the build smoke fixture rather than weakening the test.

## Task 7: Build The New Calculation Preview Workspace

**Files:**
- Create: `frontend/src/pages/competition/CompetitionNewCalculation.jsx`
- Modify: `frontend/src/pages/competition/CompetitionPages.css`
- Modify: `frontend/tests/competitionPages107Cup.test.mjs`

- [ ] **Step 1: Write the failing calculation-workspace contract**

```js
test('new calculation keeps the fixed graph and preview writes disabled', () => {
  const source = read('../src/pages/competition/CompetitionNewCalculation.jsx');
  for (const token of ['DEMO_STRUCTURE', 'VaspStructureViewer', 'relax', 'scf', 'band', 'dos', 'PreviewReadOnlyNotice']) assert.match(source, new RegExp(token, 'i'));
  assert.match(source, /disabled=\{readOnly/);
  assert.match(source, /1 MiB/);
  assert.match(source, /200/);
  assert.doesNotMatch(source, /alert\([^)]*成功/);
});
```

- [ ] **Step 2: Run the test and verify RED**

Run `cd frontend && node --test tests/competitionPages107Cup.test.mjs`.

Expected: FAIL because the page does not exist.

- [ ] **Step 3: Implement source selection and structure inspection**

Use state `sourceKind` with only `builtin` and `upload`, default `builtin`. Render a two-option segmented control, the directly reused `VaspStructureViewer` with `DEMO_STRUCTURE`, and a compact lattice summary. In demo mode the file input is disabled and its text is exactly `POSCAR/CIF 文本，最大 1 MiB，最多 200 个原子`.

Import the existing `../db/vasp-detail/VaspTaskDetail.css` so the reused viewer retains its verified canvas bounds; do not copy those rules into `CompetitionPages.css`.

Do not parse or upload a real file in this preview task. Live-mode upload remains wired only through `provider.uploadStructure` after phase 5 supplies validation and draft models.

- [ ] **Step 4: Implement the immutable four-step dependency view**

Use buttons to inspect the parameter summary for each step, but do not expose delete, drag, reorder, or add controls. Define:

```js
const WORKFLOW_STEPS = [
  { key: 'relax', label: 'relax', dependsOn: [], purpose: '优化离子位置与晶格' },
  { key: 'scf', label: 'SCF', dependsOn: ['relax'], purpose: '生成已验收自洽电荷密度' },
  { key: 'band', label: 'BAND', dependsOn: ['scf'], purpose: '沿固定高对称路径计算能带' },
  { key: 'dos', label: 'DOS', dependsOn: ['scf'], purpose: '基于自洽结果计算态密度' },
];
```

- [ ] **Step 5: Render parameter and resource review**

Show read-only summaries for template `mos2-v1`, input SHA state `提交前生成`, ENCUT/k-point/convergence headings, partition `P107-RTX5090`, maximum request `4 GPU / 16 CPU`, and one-job-per-step evidence semantics. Mark values as `演示参数`, not validated production inputs.

- [ ] **Step 6: Make every write command fail closed in the UI**

```jsx
const readOnly = mode === 'demo' || !canWriteCompetitionData(user);
const draft = {
  id: 'preview-draft',
  source_kind: sourceKind,
  template_version: 'mos2-v1',
  steps: WORKFLOW_STEPS.map((step) => step.key),
};

<button type="button" disabled={readOnly} onClick={() => provider.saveDraft(draft)}>保存草稿</button>
<button type="button" disabled={readOnly} onClick={() => provider.submitWorkflow(draft.id)}>提交四步工作流</button>
{readOnly ? <PreviewReadOnlyNotice /> : null}
```

Define `const user = readStoredUser()` with the same guarded JSON parse already used by `CompetitionDashboard`; do not infer Operator from provider mode.

The demo build must not attach an upload handler to the disabled input and must not call either method. The provider rejection remains the second enforcement layer.

- [ ] **Step 7: Run tests and commit**

```bash
cd frontend
node --test tests/competitionPages107Cup.test.mjs tests/competitionDataProvider.test.mjs
git add src/pages/competition/CompetitionNewCalculation.jsx src/pages/competition/CompetitionPages.css tests/competitionPages107Cup.test.mjs
git commit -m "feat(107cup): add calculation workspace preview"
```

Expected: tests PASS.

## Task 8: Build Workflow List And Evidence Detail

**Files:**
- Create: `frontend/src/pages/competition/CompetitionWorkflows.jsx`
- Create: `frontend/src/pages/competition/CompetitionWorkflowDetail.jsx`
- Modify: `frontend/src/pages/competition/CompetitionPages.css`
- Modify: `frontend/tests/competitionPages107Cup.test.mjs`

- [ ] **Step 1: Write failing list/detail contracts**

```js
test('workflow pages preserve searchable state and provenance', () => {
  const list = read('../src/pages/competition/CompetitionWorkflows.jsx');
  const detail = read('../src/pages/competition/CompetitionWorkflowDetail.jsx');
  for (const token of ['listWorkflows', 'query', 'status', 'CompetitionTable']) assert.match(list, new RegExp(token));
  for (const token of ['getWorkflow', 'input_sha256', 'release_commit', 'template_version', 'WorkflowTimeline', 'data_kind']) assert.match(detail, new RegExp(token));
  assert.match(detail, /disabled=\{readOnly/);
});
```

- [ ] **Step 2: Run the test and verify RED**

Run `cd frontend && node --test tests/competitionPages107Cup.test.mjs`.

Expected: FAIL because both pages do not exist.

- [ ] **Step 3: Implement query and status filters**

`CompetitionWorkflows` keeps `query` and `status` in `URLSearchParams`, calls `provider.listWorkflows({ query, status })`, and renders a search input plus status menu containing `all`, `running`, `succeeded`, and `failed`. Each row opens `/dashboard/workflows/{id}`. Loading, empty, forbidden, and error states use `CompetitionState`; demo mode always renders `DemoDataBanner`.

- [ ] **Step 4: Implement workflow identity and full evidence timeline**

Use `useParams()` and `provider.getWorkflow(workflowId)`. A missing demo ID is an explicit `empty/not found` surface. Render these immutable identity fields before the timeline:

```jsx
<dl className="competition-provenance-grid">
  <div><dt>工作流 ID</dt><dd>{workflow.id}</dd></div>
  <div><dt>创建人</dt><dd>{workflow.creator}</dd></div>
  <div><dt>模板版本</dt><dd>{workflow.template_version}</dd></div>
  <div><dt>输入 SHA-256</dt><dd>{workflow.input_sha256}</dd></div>
  <div><dt>发布提交</dt><dd>{workflow.release_commit}</dd></div>
  <div><dt>数据类型</dt><dd>{workflow.data_kind === 'demo' ? '演示数据' : '真实数据'}</dd></div>
</dl>
```

Render `WorkflowTimeline` non-compact so Job ID, attempt, directory, Slurm state, ExitCode, reason, and acceptance are visible.

- [ ] **Step 5: Add disabled cancel/retry commands**

Render icon+text commands expected by the final UI. Define `const failedStep = workflow.steps.find((step) => step.status === 'failed') || null`. In demo or Viewer mode set `disabled={readOnly}` and show `PreviewReadOnlyNotice`. Do not return a toast. In future live Operator mode cancel calls `provider.cancelWorkflow(workflow.id)`; retry is disabled when `failedStep` is null and otherwise calls `provider.retryWorkflow({ id: workflow.id, step: failedStep.key })`. Backend ownership checks remain a phase 6 requirement.

- [ ] **Step 6: Run tests and commit**

```bash
cd frontend
node --test tests/competitionPages107Cup.test.mjs tests/competitionDataProvider.test.mjs
git add src/pages/competition/CompetitionWorkflows.jsx src/pages/competition/CompetitionWorkflowDetail.jsx src/pages/competition/CompetitionPages.css tests/competitionPages107Cup.test.mjs
git commit -m "feat(107cup): add workflow evidence preview"
```

Expected: tests PASS and no page imports Slurm commands or the legacy VASP router.

## Task 9: Build Result List And Scientific Result Detail

**Files:**
- Create: `frontend/src/pages/competition/CompetitionResults.jsx`
- Create: `frontend/src/pages/competition/CompetitionResultDetail.jsx`
- Modify: `frontend/src/pages/competition/CompetitionPages.css`
- Modify: `frontend/tests/competitionPages107Cup.test.mjs`

- [ ] **Step 1: Write failing reuse and failure-state tests**

```js
test('result detail directly reuses existing scientific components', () => {
  const source = read('../src/pages/competition/CompetitionResultDetail.jsx');
  for (const component of ['VaspStructureViewer', 'VaspCrystalDetails', 'VaspElectronicProperties', 'VaspTaskSummary']) assert.match(source, new RegExp(component));
  assert.match(source, /failure_evidence/);
  assert.match(source, /parse-error/);
  assert.doesNotMatch(source, /backend\/routers\/vasp_db|PersonalVaspDatabase/);
});

test('result list separates succeeded and failed records', () => {
  const source = read('../src/pages/competition/CompetitionResults.jsx');
  assert.match(source, /listResults/);
  assert.match(source, /succeeded/);
  assert.match(source, /failed/);
  assert.match(source, /CompetitionTable/);
});
```

- [ ] **Step 2: Run the test and verify RED**

Run `cd frontend && node --test tests/competitionPages107Cup.test.mjs`.

Expected: FAIL because both result pages do not exist.

- [ ] **Step 3: Implement the result list**

Use the same URL-backed query and status pattern as workflows, but call `provider.listResults`. Rows open `/dashboard/results/{workflowId}`. The status filter includes `all`, `succeeded`, `failed`, and `parse-error`. Do not treat running workflows as completed results.

- [ ] **Step 4: Implement a scientific adapter for reused components**

Inside `CompetitionResultDetail`, define adapters over the provider rather than importing the legacy router:

Import `../db/vasp-detail/VaspTaskDetail.css` before rendering the reused detail components.

```js
const inferArtifactKind = (value) => {
  const text = String(value).toLowerCase();
  if (text.includes('band')) return 'band-data';
  if (text.includes('dos')) return 'dos-data';
  if (text.includes('cif')) return 'structure-cif';
  if (text.includes('poscar') || text.includes('.vasp')) return 'structure-poscar';
  return 'evidence-bundle';
};

const fetchScientificJson = async (path) => {
  const kind = path.includes('band-plot') ? 'band' : 'dos';
  return provider.loadPlot(workflowId, kind);
};

const downloadScientificFile = async (path, filename) => {
  const artifact = await provider.downloadArtifact(workflowId, inferArtifactKind(`${path} ${filename}`));
  const href = URL.createObjectURL(artifact.blob);
  const anchor = document.createElement('a');
  anchor.href = href;
  anchor.download = artifact.filename;
  anchor.click();
  URL.revokeObjectURL(href);
};
```

The demo provider returns a `Blob` generated from version-controlled fixture text/JSON; it does not fetch a server URL.

- [ ] **Step 5: Render successful results with direct scientific reuse**

Map the fixture to the existing detail shape and render:

```jsx
<section className="competition-result-science">
  <VaspTaskSummary
    detail={result.vasp_detail}
    dbKey="107cup-demo"
    rowId={workflowId}
    viewer={<VaspStructureViewer structure={result.vasp_detail.structure} />}
    downloadFile={downloadScientificFile}
  />
  <VaspCrystalDetails detail={result.vasp_detail} />
  <VaspElectronicProperties
    rowId={workflowId}
    dbKey="107cup-demo"
    capabilities={result.vasp_detail.capabilities}
    fetchJson={fetchScientificJson}
    downloadFile={downloadScientificFile}
  />
</section>
```

Show the provenance identity block and full workflow timeline above this section. Every demo download filename starts with `DEMO-` and the UI labels it `演示内容`.

- [ ] **Step 6: Render failures without blank success charts**

If `result.status === 'failed'` or `result.status === 'parse-error'`, render `failure_evidence` with failed step, Job ID, ExitCode, reason, expected files, missing files, and last log lines. Do not mount `VaspElectronicProperties` or show download buttons for absent artifacts.

- [ ] **Step 7: Run tests and commit**

```bash
cd frontend
node --test tests/competitionPages107Cup.test.mjs tests/vaspTaskDetailPresentation.test.mjs tests/competitionDataProvider.test.mjs
git add src/pages/competition/CompetitionResults.jsx src/pages/competition/CompetitionResultDetail.jsx src/pages/competition/CompetitionPages.css tests/competitionPages107Cup.test.mjs
git commit -m "feat(107cup): add scientific result preview"
```

Expected: all focused tests PASS.

## Task 10: Build The Periodic-Table VASP Database And Integrate Routes

**Files:**
- Create: `frontend/src/pages/competition/CompetitionVaspDatabase.jsx`
- Modify: `frontend/src/pages/competition/CompetitionPages.css`
- Modify: `frontend/src/App107Cup.jsx`
- Modify: `frontend/src/config/appNavigation.js`
- Modify: `frontend/src/components/AppShell.jsx`
- Modify: `frontend/src/components/AppShell.css`
- Modify: `frontend/tests/appNavigation107Cup.test.mjs`
- Modify: `frontend/tests/competitionRoles107Cup.test.mjs`
- Modify: `frontend/tests/competitionPages107Cup.test.mjs`

- [ ] **Step 1: Add the failing database page contract**

```js
test('competition VASP database composes the extracted read-only units', () => {
  const source = read('../src/pages/competition/CompetitionVaspDatabase.jsx');
  for (const token of ['PeriodicTableFilter', 'VaspRecordTable', 'getDatabaseRecord', 'available_elements', 'elementMode', 'selectedElements']) assert.match(source, new RegExp(token));
  assert.match(source, /VaspStructureViewer/);
  assert.doesNotMatch(source, /onCollect|onRemove|customDbs|uploadFiles/);
});
```

Also make the route test require all seven protected paths only at this task, so every commit before route integration remains buildable.

- [ ] **Step 2: Run the tests and verify RED**

```bash
cd frontend
node --test tests/competitionPages107Cup.test.mjs tests/appNavigation107Cup.test.mjs tests/competitionRoles107Cup.test.mjs
```

Expected: FAIL for the missing database page and missing routes.

- [ ] **Step 3: Implement database filters and URL state**

Maintain `query`, `selectedElements`, `elementMode`, `page`, and `selectedRecordId`. Serialize them as `q`, `elements`, `element_mode`, `page`, and `record` in `URLSearchParams`. Call:

```js
provider.listDatabase({
  query,
  elements: selectedElements,
  elementMode,
  page,
  pageSize: 20,
});
```

Render `PeriodicTableFilter` using `result.available_elements`, then the query input and result count. Clearing elements resets page to 1.

- [ ] **Step 4: Render the extracted read-only table**

Use columns exactly:

```js
const DATABASE_COLUMNS = ['formula', 'source', 'workflow_id', 'status', 'bandgap_eV', 'energy', 'completed_at'];
```

Map each demo row to `_rowId: row.id` and call:

```jsx
<VaspRecordTable
  records={result.items}
  columns={DATABASE_COLUMNS}
  metadata={result.metadata}
  loading={state.status === 'loading'}
  loadedOnce={state.status !== 'loading'}
  detailPathForItem={(item) => `/dashboard/database/vasp?record=${encodeURIComponent(item.id)}`}
  onSelect={(item) => setSelectedRecordId(item.id)}
  renderCell={(column, item) => column === 'status' ? <StatusBadge status={item.status} /> : undefined}
  mobileMode="scroll"
/>
```

There is no `renderActions` prop, so no operation column, favorite, removal, or upload action appears.

- [ ] **Step 5: Render the selected record inspection panel**

When `record` exists, call `provider.getDatabaseRecord(record)` and render composition, source workflow, status, band gap, total energy, completion time, latest demo Job ID, BAND/DOS availability, evidence-bundle state, and `VaspStructureViewer`. At desktop use a two-column unframed work area; at 1024px and below stack the inspector after the table.

Import the existing `../db/vasp-detail/VaspTaskDetail.css` for the selected-record structure viewer.

- [ ] **Step 6: Integrate navigation, provider shell, and all routes**

Now that every lazy page exists, add the protected provider shell:

```jsx
function ProtectedCompetitionShell() {
  return (
    <RequireAuth>
      <CompetitionDataProvider>
        <AppShell />
      </CompetitionDataProvider>
    </RequireAuth>
  );
}
```

`App107Cup.jsx` must lazy-import only:

```js
Login
CompetitionDashboard
CompetitionNewCalculation
CompetitionWorkflows
CompetitionWorkflowDetail
CompetitionResults
CompetitionResultDetail
CompetitionVaspDatabase
```

Add these exact protected routes:

```jsx
<Route element={<ProtectedCompetitionShell />}>
  <Route path="/dashboard" element={<CompetitionDashboard />} />
  <Route path="/dashboard/calculations/new" element={<CompetitionNewCalculation />} />
  <Route path="/dashboard/workflows" element={<CompetitionWorkflows />} />
  <Route path="/dashboard/workflows/:workflowId" element={<CompetitionWorkflowDetail />} />
  <Route path="/dashboard/results" element={<CompetitionResults />} />
  <Route path="/dashboard/results/:workflowId" element={<CompetitionResultDetail />} />
  <Route path="/dashboard/database/vasp" element={<CompetitionVaspDatabase />} />
</Route>
```

Unknown routes still navigate to `/dashboard`; unauthenticated refresh remains controlled by `RequireAuth`. `App107Cup.jsx` must not import `Dashboard`, `PersonalVaspDatabase`, standard database layouts, Agents, reports, notes, or monitoring routes.

Import `SquarePlus`, `Workflow`, and `ChartNoAxesCombined` from Lucide into `AppShell`, add them to `iconMap`, and derive `const competitionDemo = activeEdition === '107cup' && import.meta.env.VITE_COMPETITION_DATA_MODE === 'demo'`. Render this compact marker when `competitionDemo` is true, without importing the fixture provider into the standard app shell:

```jsx
<span className="lm-demo-build-badge" title="此发布只使用版本控制内的演示数据">演示数据</span>
```

At 390px it remains visible without overlapping the account button.

- [ ] **Step 7: Verify route refresh build output**

```bash
cd frontend
node --test tests/appNavigation107Cup.test.mjs tests/competitionRoles107Cup.test.mjs tests/competitionPages107Cup.test.mjs
VITE_LMATELAB_EDITION=107cup VITE_COMPETITION_DATA_MODE=demo npm run build
rg -n "Agent|PersonalVaspDatabase|ServerMonitor|AcademicReports" dist/assets
```

Expected: tests and build PASS; `rg` returns no unrelated page module names. The FastAPI SPA resolver is already responsible for direct-refresh fallback and is rechecked later by backend tests.

- [ ] **Step 8: Commit database and route integration**

```bash
git add frontend/src/pages/competition/CompetitionVaspDatabase.jsx frontend/src/pages/competition/CompetitionPages.css frontend/src/App107Cup.jsx frontend/src/config/appNavigation.js frontend/src/components/AppShell.jsx frontend/src/components/AppShell.css frontend/tests/appNavigation107Cup.test.mjs frontend/tests/competitionRoles107Cup.test.mjs frontend/tests/competitionPages107Cup.test.mjs
git commit -m "feat(107cup): complete frontend preview routes"
```

## Task 11: Add Responsive Browser Acceptance With Canvas Pixel Checks

The three mandatory viewport gates are exactly `1440x900`, `1024x768`, and `390x844`.

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/package-lock.json`
- Create: `frontend/playwright.config.js`
- Create: `frontend/e2e/competition-preview.spec.js`
- Modify: `.gitignore`

- [ ] **Step 1: Add browser-test dependencies mechanically**

Run on the implementation workstation, not the 107 login node:

```bash
cd frontend
npm install --save-dev @playwright/test@1.54.2 pngjs@7.0.0
npx playwright install chromium
```

Add:

```json
"test:e2e": "playwright test"
```

Expected: `package.json` and `package-lock.json` change; Chromium installation completes in the workstation cache.

- [ ] **Step 2: Create an external-target-only Playwright config**

```js
import { defineConfig } from '@playwright/test';

const baseURL = process.env.LMATELAB_PREVIEW_URL;
if (!baseURL) throw new Error('LMATELAB_PREVIEW_URL is required; this suite never starts a login-node web server');

const viewports = [
  { name: 'desktop', width: 1440, height: 900 },
  { name: 'compact', width: 1024, height: 768 },
  { name: 'mobile', width: 390, height: 844 },
];

export default defineConfig({
  testDir: './e2e',
  timeout: 45_000,
  retries: 0,
  use: { baseURL, trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  outputDir: 'test-results/competition-preview',
  projects: viewports.map(({ name, width, height }) => ({ name, use: { viewport: { width, height } } })),
});
```

Add `/frontend/test-results/` and `/frontend/playwright-report/` to `.gitignore`.

- [ ] **Step 3: Write the login helper and network/console guards**

```js
async function login(page) {
  await page.goto('/login');
  await page.locator('input[name="email"]').fill(process.env.LMATELAB_E2E_EMAIL);
  await page.locator('input[name="password"]').fill(process.env.LMATELAB_E2E_PASSWORD);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL('**/dashboard');
}

function collectViolations(page) {
  const consoleProblems = [];
  const businessWrites = [];
  page.on('console', (message) => {
    if (['error', 'warning'].includes(message.type())) consoleProblems.push(`${message.type()}: ${message.text()}`);
  });
  page.on('request', (request) => {
    if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(request.method()) && !request.url().endsWith('/api/auth/login')) businessWrites.push(`${request.method()} ${request.url()}`);
  });
  return { consoleProblems, businessWrites };
}
```

- [ ] **Step 4: Test all routes, refreshes, and disabled writes at three viewports**

For every configured viewport, log in once and visit/refresh:

```js
const routes = ['/dashboard', '/dashboard/calculations/new', '/dashboard/workflows', '/dashboard/results', '/dashboard/database/vasp'];
```

Assert `演示数据` is visible after navigation and reload, `document.documentElement.scrollWidth <= window.innerWidth + 1`, disabled upload/save/submit controls are disabled, and `businessWrites` stays empty.

- [ ] **Step 5: Test interactive filters, tabs, timeline, and canvas pixels**

Use the periodic table to select Mo and S, switch between `至少含有` and `只含`, clear selection, open the successful result, switch BAND/DOS tabs, and click the reset-view icon. Decode the 3D canvas screenshot using `pngjs`:

```js
import { PNG } from 'pngjs';

const canvas = page.locator('.vasp-viewer-canvas canvas');
await expect(canvas).toBeVisible();
const png = PNG.sync.read(await canvas.screenshot());
let colored = 0;
for (let index = 0; index < png.data.length; index += 4) {
  const [r, g, b, a] = png.data.subarray(index, index + 4);
  if (a > 0 && (r < 245 || g < 245 || b < 245)) colored += 1;
}
expect(colored).toBeGreaterThan(png.width * png.height * 0.002);
```

This is the required nonblank canvas-pixel check; file-size-only assertions are insufficient.

- [ ] **Step 6: Capture deliberate evidence screenshots**

For each viewport capture dashboard, calculation, successful result, failed result, and database to an external evidence root supplied as `LMATELAB_E2E_EVIDENCE_DIR`. The test must fail if that environment variable or `LMATELAB_PREVIEW_COMMIT` is absent:

```js
const evidenceRoot = process.env.LMATELAB_E2E_EVIDENCE_DIR;
const previewCommit = process.env.LMATELAB_PREVIEW_COMMIT;
if (!evidenceRoot || !previewCommit) throw new Error('external evidence directory and preview commit are required');

async function captureEvidence(page, testInfo, routeName) {
  mkdirSync(evidenceRoot, { recursive: true });
  const timestamp = new Date().toISOString().replaceAll(':', '-');
  const filename = `${testInfo.project.name}-${routeName}-${previewCommit}-${timestamp}.png`;
  await page.screenshot({ path: join(evidenceRoot, filename), fullPage: true });
}
```

Import `mkdirSync` from `node:fs` and `join` from `node:path`. Do not commit screenshots into the source tree.

- [ ] **Step 7: Run only after the 107 preview is live**

PowerShell:

```powershell
$previewCommit=$env:LMATELAB_PREVIEW_COMMIT
if (-not $previewCommit) { throw 'LMATELAB_PREVIEW_COMMIT must equal the verified merged main commit' }
$verifiedPreviewUrl='http://127.0.0.1:18735'
$env:LMATELAB_PREVIEW_URL=$verifiedPreviewUrl
$env:LMATELAB_PREVIEW_COMMIT=$previewCommit
if (-not $env:LMATELAB_E2E_EMAIL) { throw 'LMATELAB_E2E_EMAIL must contain the private preview account email' }
if (-not $env:LMATELAB_E2E_PASSWORD) { throw 'LMATELAB_E2E_PASSWORD must contain the private preview account password' }
$env:LMATELAB_E2E_EVIDENCE_DIR="D:\Documents\matflow项目\LMateLab-107Cup-evidence\frontend-preview-$previewCommit"
cd D:\Documents\matflow项目\LMateLab-107Cup\frontend
npm run test:e2e
```

Expected: all three viewport projects PASS, zero relevant console warnings/errors, zero business writes, and nonblank 3D pixels. `$verifiedPreviewUrl` and `$previewCommit` must come from the deployed preview status; never commit credentials.

- [ ] **Step 8: Commit browser acceptance code**

```bash
git add frontend/package.json frontend/package-lock.json frontend/playwright.config.js frontend/e2e/competition-preview.spec.js .gitignore
git commit -m "test(107cup): add browser preview acceptance"
```

## Task 12: Build An Isolated 107 Slurm Preview Release And Service

**Files:**
- Create: `deploy/107cup/preview-build.slurm`
- Create: `deploy/107cup/submit-preview-build.sh`
- Create: `deploy/107cup/preview-service.slurm`
- Create: `deploy/107cup/submit-preview-service.sh`
- Create: `deploy/107cup/verify-preview-runtime.sh`
- Create: `deploy/107cup/preview-snapshot.slurm`
- Create: `deploy/107cup/submit-preview-snapshot.sh`
- Create: `backend/tests/test_107cup_preview_deploy_contract.py`
- Modify: `backend/competition_runtime.py`
- Modify: `backend/tests/test_107cup_runtime.py`
- Modify: `deploy/107cup/build.slurm`
- Modify: `deploy/107cup/runtime.env.example`

- [ ] **Step 1: Write failing deployment isolation tests**

Create a Python `unittest` that reads all preview scripts and asserts:

```python
def test_preview_build_never_promotes_current(self):
    source = self.read_required("preview-build.slurm")
    for required in ("SLURM_JOB_ID", "LMATELAB_PREVIEW_COMMIT", "origin/main", "previews", "VITE_COMPETITION_DATA_MODE=demo", "manifest.sha256", "npm ci", "npm test"):
        self.assertIn(required, source)
    for forbidden in ("current.next", 'mv -Tf "$root/current.next"', 'printf \'%s\\n\' "$commit" > "$root/runtime/build-commit"'):
        self.assertNotIn(forbidden, source)

def test_preview_service_uses_private_data_runtime_and_port(self):
    source = self.read_required("preview-service.slurm")
    for required in ("preview-runtime", "sqlite3", ".backup", "LMATELAB_RELEASE_KIND=preview", "LMATELAB_DATA_MODE=demo", "preview-service-port", "uvicorn main_107cup:app", "--workers 1"):
        self.assertIn(required, source)
    self.assertNotIn('readlink -f "$root/current"', source)
    self.assertNotIn('DATABASE_URL=sqlite:////home/scc/pb23030683/lmatelab-107cup/data/db/eln.db', source)

def test_login_node_helpers_only_fetch_submit_and_verify(self):
    for name in ("submit-preview-build.sh", "submit-preview-service.sh", "submit-preview-snapshot.sh", "verify-preview-runtime.sh"):
        source = self.read_required(name)
        for forbidden in ("npm ci", "npm run build", "pip install", "uvicorn ", "alembic "):
            self.assertNotIn(forbidden, source)
```

Also extend metadata expectations with `release_kind` and `data_mode`, ensuring `JWT_SECRET` remains absent.

- [ ] **Step 2: Run the backend tests and verify RED**

```bash
cd backend
python -m unittest tests.test_107cup_preview_deploy_contract tests.test_107cup_runtime -v
```

Expected: FAIL because the preview scripts and metadata fields do not exist.

- [ ] **Step 3: Add non-secret preview metadata**

```python
return {
    "job_id": values.get("SLURM_JOB_ID", "unknown"),
    "node": values.get("SLURMD_NODENAME", values.get("HOSTNAME", "unknown")),
    "commit": values.get("LMATELAB_GIT_COMMIT", "unknown"),
    "manifest_sha256": values.get("LMATELAB_MANIFEST_SHA256", "unknown"),
    "started_at": values.get("LMATELAB_STARTED_AT", "unknown"),
    "release_kind": values.get("LMATELAB_RELEASE_KIND", "stable"),
    "data_mode": values.get("LMATELAB_DATA_MODE", "live"),
}
```

Add `LMATELAB_RELEASE_KIND=stable` and `LMATELAB_DATA_MODE=live` to `runtime.env.example`. Make stable `build.slurm` build with both `VITE_LMATELAB_EDITION=107cup` and `VITE_COMPETITION_DATA_MODE=live`; this only fixes the future stable build mode and must not trigger a stable rebuild in this task.

- [ ] **Step 4: Implement the preview build job**

The Slurm header mirrors the existing build job but uses job name `lmatelab-preview-build`, output/error `logs/preview-build-%j.*`, and time `00:45:00`. The body must:

```bash
set -euo pipefail
: "${SLURM_JOB_ID:?preview-build.slurm must run through Slurm}"
: "${LMATELAB_PREVIEW_COMMIT:?fixed merge commit is required}"
[[ "$LMATELAB_PREVIEW_COMMIT" =~ ^[0-9a-f]{40}$ ]]

root=/home/scc/pb23030683/lmatelab-107cup
project=/home/scc/pb23030683/projects/LMateLab-107Cup
commit="$LMATELAB_PREVIEW_COMMIT"
test "$(git -C "$project" rev-parse origin/main)" = "$commit"
git -C "$project" merge-base --is-ancestor "$commit" origin/main

release="$root/previews/$commit"
staging="$root/previews/.$commit.$SLURM_JOB_ID"
python_env="$root/preview-envs/python/$commit"
source_tree="$staging/source"
mkdir -p "$root/previews" "$root/preview-envs/python" "$root/logs"
test ! -e "$staging"
mkdir -p "$source_tree"
git -C "$project" archive "$commit" | tar -C "$source_tree" -xf -
```

Bootstrap the existing pinned Node version and a commit-specific Python venv inside the Slurm job:

```bash
source /etc/profile.d/modules.sh
module load miniconda/py312
node_version=v22.14.0
node_name="node-$node_version-linux-x64"
node_root="$root/envs/$node_name"
if ! test -x "$node_root/bin/node"; then
  tmp_root="${SLURM_TMPDIR:-/tmp}"
  curl --fail --location --silent --show-error "https://nodejs.org/dist/$node_version/$node_name.tar.xz" --output "$tmp_root/$node_name.tar.xz"
  curl --fail --location --silent --show-error "https://nodejs.org/dist/$node_version/SHASUMS256.txt" --output "$tmp_root/node-sha256.txt"
  (cd "$tmp_root" && grep "  $node_name.tar.xz$" node-sha256.txt | sha256sum -c -)
  node_staging="$root/envs/.$node_name.$SLURM_JOB_ID"
  test ! -e "$node_staging"
  mkdir -p "$node_staging"
  tar -xJf "$tmp_root/$node_name.tar.xz" -C "$node_staging" --strip-components=1
  mv "$node_staging" "$node_root"
fi
export PATH="$node_root/bin:$PATH"

if ! test -x "$python_env/bin/python"; then
  python -m venv "$python_env"
fi
source "$python_env/bin/activate"
python -m pip install --upgrade pip
python -m pip install --requirement "$source_tree/backend/requirements-107cup.txt"
```

Run the exact backend and frontend checks:

```bash
cd "$source_tree/backend"
python -m unittest \
  tests.test_107cup_authz \
  tests.test_107cup_runtime \
  tests.test_107cup_deploy_contract \
  tests.test_107cup_preview_deploy_contract \
  tests.test_health_readiness \
  -v
cd "$source_tree/frontend"
npm ci
npm test
VITE_LMATELAB_EDITION=107cup VITE_COMPETITION_DATA_MODE=demo npm run build
```

Copy `frontend/dist` to `$staging/frontend-dist`, remove only `$source_tree/frontend/node_modules` and `$source_tree/frontend/dist`, write `commit.txt`, `release-kind.txt` containing `preview`, `data-mode.txt` containing `demo`, `manifest.txt`, and `manifest.sha256`, verify both manifests, then atomically rename only `$staging` to `$release`. If `$release` already exists, verify its manifests and exit without rebuilding. Never create or modify `current`, stable runtime files, or stable databases.

- [ ] **Step 5: Implement the short preview-build submit helper**

```bash
#!/bin/bash
set -euo pipefail
project=/home/scc/pb23030683/projects/LMateLab-107Cup
root=/home/scc/pb23030683/lmatelab-107cup
commit="${1:?usage: submit-preview-build.sh MERGED_MAIN_COMMIT}"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]]
git -C "$project" fetch --quiet origin main
test "$(git -C "$project" rev-parse origin/main)" = "$commit"
mkdir -p "$root/logs" "$root/runtime/previews/$commit"
job_id=$(sbatch --parsable --export=ALL,LMATELAB_PREVIEW_COMMIT="$commit" "$project/deploy/107cup/preview-build.slurm")
printf '%s\n' "$job_id" > "$root/runtime/previews/$commit/build-job-id"
printf '%s\n' "$job_id"
```

This fetch is short and non-build work; it is allowed on the login node.

- [ ] **Step 6: Implement a private preview service job**

Use job name `lmatelab-preview-web`, a maximum time of `2-00:00:00`, one task, two CPUs, 8 GiB, no `--gres`, and the competition QOS. Start with `set -euo pipefail`, `umask 077`, validate `SLURM_JOB_ID` and the 40-character `LMATELAB_PREVIEW_COMMIT`, then define and validate:

```bash
root=/home/scc/pb23030683/lmatelab-107cup
commit="$LMATELAB_PREVIEW_COMMIT"
release="$root/previews/$commit"
python_env="$root/preview-envs/python/$commit"
runtime_env="$root/config/runtime.env"
test -d "$release"
test -x "$python_env/bin/python"
test -f "$runtime_env"
(cd "$release" && sha256sum -c manifest.sha256 && sha256sum -c manifest.txt)
```

Then create:

```bash
runtime="$root/preview-runtime/$commit/$SLURM_JOB_ID"
data="$runtime/data"
mkdir -p "$data/db" "$runtime/cache/matplotlib" "$runtime/cache/vasp-elements"
chmod 700 "$runtime" "$data" "$data/db"

"$python_env/bin/python" - "$root/data/db/eln.db" "$data/db/eln.db" "$root/data/db/digests.db" "$data/db/digests.db" <<'PY'
import sqlite3
import sys

for source_path, target_path in zip(sys.argv[1::2], sys.argv[2::2]):
    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    target = sqlite3.connect(target_path)
    try:
        source.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError(f"preview database integrity failed: {target_path}")
    finally:
        target.close()
        source.close()
PY

port=$((20000 + SLURM_JOB_ID % 1000))
if ss -ltnH "sport = :$port" | grep -q .; then
  printf 'preview port already in use: %s\n' "$port" >&2
  exit 1
fi
```

Source stable `runtime.env` only for JWT/config defaults, then override every writable value:

```bash
export DATABASE_URL="sqlite:///$data/db/eln.db"
export DIGEST_DATABASE_URL="sqlite:///$data/db/digests.db"
export LMATELAB_DATA_DIR="$data"
export UPLOADS_ROOT="$data/uploads"
export VASP_UPLOADS_ROOT="$data/uploads"
export VASP_CUSTOM_DB_ROOT="$data/custom/vasp"
export QE_EPW_CUSTOM_DB_ROOT="$data/custom/qe_epw"
export VASP_ELEMENTS_CACHE_DIR="$runtime/cache/vasp-elements"
export ISSUES_DIR="$data/issues"
export CHANGELOG_PATH="$data/changelog.md"
export ACADEMIC_REPORTS_FILE="$data/academic_reports.json"
export MPLCONFIGDIR="$runtime/cache/matplotlib"
export LMATELAB_FRONTEND_DIST="$release/frontend-dist"
export LMATELAB_GIT_COMMIT="$commit"
export LMATELAB_MANIFEST_SHA256="$(cut -d ' ' -f 1 "$release/manifest.sha256")"
export LMATELAB_STARTED_AT="$(date --iso-8601=seconds)"
export LMATELAB_RELEASE_KIND=preview
export LMATELAB_DATA_MODE=demo
```

Create the writable directories, run migrations only against copied databases, write `preview-service-job-id`, `preview-service-node`, `preview-service-port`, `preview-service-commit`, and `preview-service-manifest-sha256` under `$runtime`, then `exec uvicorn main_107cup:app --host 0.0.0.0 --port "$port" --workers 1` using the commit-specific preview venv.

- [ ] **Step 7: Implement submit and runtime verification helpers**

`submit-preview-service.sh COMMIT` verifies the preview manifests and submits with `--export=ALL,LMATELAB_PREVIEW_COMMIT="$commit"`; it writes only the returned Job ID under `runtime/previews/$commit/last-service-job-id`.

`verify-preview-runtime.sh COMMIT JOB_ID [running|stopped]` must:

1. Validate both arguments with strict regex.
2. Read node/port/manifest from `preview-runtime/$commit/$job_id`.
3. Run `squeue` and `sacct` read-only queries.
4. Recheck the release manifests.
5. In `running` mode, require `/api/health/live` to report the exact Job ID, node, commit, `release_kind=preview`, and `data_mode=demo`, then require `/api/health/ready`.
6. In `stopped` mode, require `curl --connect-timeout 3` to fail for the recorded node/port.
7. Reject any login-node `uvicorn`, Vite, Celery, or Redis process just as `verify-runtime.sh` does.

- [ ] **Step 8: Add before/after stable snapshots in a short Slurm job**

`preview-snapshot.slurm` accepts `LMATELAB_PREVIEW_COMMIT` and `LMATELAB_PREVIEW_SNAPSHOT_PHASE=before|after`, runs for `00:05:00`, and writes private evidence under `$root/evidence/previews/$commit/$phase-$SLURM_JOB_ID`. It records:

```text
current-target.txt
stable-eln.sha256
stable-digests.sha256
stable-eln-integrity.txt
stable-digests-integrity.txt
stable-service-job-id.txt
stable-service-node.txt
stable-service-port.txt
stable-service-commit.txt
stable-health-live.json
squeue.txt
sacct.txt
manifest.sha256
```

The `after` job receives `LMATELAB_PREVIEW_BEFORE_DIR`, rechecks every saved SHA-256 and current/service field with `cmp`, and fails if any stable target changed. It is allowed to read `current` and stable databases but may not write them. `submit-preview-snapshot.sh PHASE COMMIT [BEFORE_DIR]` only validates inputs and calls `sbatch`.

- [ ] **Step 9: Run all deployment contract tests**

```bash
cd backend
python -m unittest \
  tests.test_107cup_preview_deploy_contract \
  tests.test_107cup_deploy_contract \
  tests.test_107cup_runtime \
  tests.test_health_readiness \
  -v
```

Expected: all tests PASS. Existing stable script contracts remain green.

- [ ] **Step 10: Commit preview deployment code**

```bash
git add deploy/107cup/preview-build.slurm deploy/107cup/submit-preview-build.sh deploy/107cup/preview-service.slurm deploy/107cup/submit-preview-service.sh deploy/107cup/verify-preview-runtime.sh deploy/107cup/preview-snapshot.slurm deploy/107cup/submit-preview-snapshot.sh deploy/107cup/build.slurm deploy/107cup/runtime.env.example backend/competition_runtime.py backend/tests/test_107cup_runtime.py backend/tests/test_107cup_preview_deploy_contract.py
git commit -m "feat(107cup): add isolated frontend preview deployment"
```

## Task 13: Verify, Merge, Deploy, Inspect, Stop, And Record Evidence

**Files:**
- Modify: `docs/107cup/implementation-plan.md`
- Create after runtime acceptance: `docs/107cup/frontend-preview-evidence.md`

- [ ] **Step 1: Run the complete local preflight**

```bash
cd backend
python -m unittest \
  tests.test_107cup_authz \
  tests.test_107cup_runtime \
  tests.test_107cup_deploy_contract \
  tests.test_107cup_preview_deploy_contract \
  tests.test_health_readiness \
  -v
cd ../frontend
npm test
VITE_LMATELAB_EDITION=107cup VITE_COMPETITION_DATA_MODE=demo npm run build
npx eslint src/App107Cup.jsx src/config/appNavigation.js src/components/AppShell.jsx src/features/competition src/pages/CompetitionDashboard.jsx src/pages/competition src/pages/db/PeriodicTableFilter.jsx src/pages/db/VaspRecordTable.jsx src/pages/db/vasp-detail/VaspStructureViewer.jsx src/pages/db/vasp-detail/VaspElectronicProperties.jsx
cd ..
git diff --check
git status --short
```

Expected: backend tests, frontend tests, demo build, targeted ESLint, and diff check all PASS. `git status` contains only intentional implementation changes before the final commit.

- [ ] **Step 2: Record only local implementation facts in the roadmap**

Append a dated entry stating the five pages and demo provider are implemented locally, list the exact test counts and build command, state that phases 5-8 remain `PENDING`, and state that 107 preview deployment/browser acceptance are not yet verified. Do not mark the preview complete at this point.

- [ ] **Step 3: Commit and push the implementation branch**

```bash
git add docs/107cup/implementation-plan.md
git commit -m "docs(107cup): record frontend preview preflight"
git push -u origin codex/107cup-frontend-preview
```

Expected: push succeeds. Create a Gitea PR into protected `main`; do not deploy the unmerged branch.

- [ ] **Step 4: Stop at the PR merge gate**

The user merges the PR through the protected-branch UI. Then verify from Windows:

```powershell
git fetch origin main
git rev-parse origin/main
git merge-base --is-ancestor codex/107cup-frontend-preview origin/main
```

Expected: the first command prints the fixed merge commit and the ancestor check exits 0. Record that 40-character merge commit as `PREVIEW_COMMIT`.

- [ ] **Step 5: Refresh the 107 read-only checkout and take the before snapshot**

After interactive SSH authentication, run only short commands on the login node:

```bash
cd /home/scc/pb23030683/projects/LMateLab-107Cup
git fetch origin main
PREVIEW_COMMIT=$(git rev-parse origin/main)
test "$PREVIEW_COMMIT" = "$(git rev-parse origin/main^{commit})"
git checkout --detach "$PREVIEW_COMMIT"
BEFORE_SNAPSHOT_JOB_ID=$(bash deploy/107cup/submit-preview-snapshot.sh before "$PREVIEW_COMMIT")
BEFORE_EVIDENCE_DIR="/home/scc/pb23030683/lmatelab-107cup/evidence/previews/$PREVIEW_COMMIT/before-$BEFORE_SNAPSHOT_JOB_ID"
printf '%s\n' "$PREVIEW_COMMIT" "$BEFORE_SNAPSHOT_JOB_ID" "$BEFORE_EVIDENCE_DIR"
```

Expected: checkout is detached at the fixed merged main commit and `sbatch` returns a real snapshot Job ID. Wait with `squeue`/`sacct`; require `COMPLETED/0:0` and save the emitted before-evidence directory.

- [ ] **Step 6: Submit and verify the preview build**

```bash
PREVIEW_BUILD_JOB_ID=$(bash deploy/107cup/submit-preview-build.sh "$PREVIEW_COMMIT")
printf '%s\n' "$PREVIEW_BUILD_JOB_ID"
```

Expected: a real build Job ID. Query until terminal, then require Slurm `COMPLETED/0:0`, backend/frontend tests in the log, demo-mode Vite build success, and both manifest checks. Verify `readlink -f /home/scc/pb23030683/lmatelab-107cup/current` still equals the before snapshot.

- [ ] **Step 7: Submit and verify the independent preview service**

```bash
PREVIEW_SERVICE_JOB_ID=$(bash deploy/107cup/submit-preview-service.sh "$PREVIEW_COMMIT")
bash deploy/107cup/verify-preview-runtime.sh "$PREVIEW_COMMIT" "$PREVIEW_SERVICE_JOB_ID" running
```

Expected: health JSON identifies the preview Job ID, node, fixed merge commit, `preview`, and `demo`; readiness is 200; the stable service Job remains running and unchanged.

- [ ] **Step 8: Establish a separate Windows preview tunnel**

Read `preview-service-node` and `preview-service-port` from the preview runtime status, then open this command in a normal interactive PowerShell window so keyboard-interactive second-factor input is possible:

```powershell
$previewNode = $env:LMATELAB_PREVIEW_NODE
$previewPort = $env:LMATELAB_PREVIEW_PORT
if (-not $previewNode -or -not $previewPort) { throw 'Set preview node and port from the verified preview runtime status' }
ssh -o IdentitiesOnly=yes -i "$env:USERPROFILE\.ssh\id_ed25519_107cup" -N -L "18735:${previewNode}:${previewPort}" pb23030683@107.ustc.edu.cn
```

Keep that window open and use `$verifiedPreviewUrl = 'http://127.0.0.1:18735'`. Do not repoint the stable `127.0.0.1:18733`/4090 upstream. Verify `$verifiedPreviewUrl/api/health/live` equals the direct preview health metadata before opening the browser. If the competition later requires team-visible review, a separate 4090 read-only upstream may replace this temporary tunnel only after its own allowlist and stable-upstream comparison pass.

- [ ] **Step 9: Run the Playwright three-viewport acceptance**

Run Task 11 Step 7 with the verified forwarded URL and preview credentials. Require all tests, canvas pixels, screenshots, direct-refresh checks, disabled writes, and zero console problems to pass. A Vite build or health response cannot substitute for this browser gate.

- [ ] **Step 10: Stop the preview and prove the port disappears**

```bash
scancel "$PREVIEW_SERVICE_JOB_ID"
bash deploy/107cup/verify-preview-runtime.sh "$PREVIEW_COMMIT" "$PREVIEW_SERVICE_JOB_ID" stopped
```

Expected: the exact preview Job reaches a terminal state, uvicorn logs a graceful shutdown, and the recorded node/port is no longer reachable. Do not cancel or restart the stable service Job.

- [ ] **Step 11: Take the after snapshot and compare stable state**

```bash
bash deploy/107cup/submit-preview-snapshot.sh after "$PREVIEW_COMMIT" "$BEFORE_EVIDENCE_DIR"
```

Expected: snapshot Job `COMPLETED/0:0`; `current`, both stable DB hashes/integrity results, stable Job ID/node/port/commit, and stable health metadata match the before snapshot.

- [ ] **Step 12: Create an evidence worktree and write exact facts**

Under `superpowers:using-git-worktrees`, create the documentation worktree from updated protected `main` before editing evidence:

```powershell
Set-Location 'D:\Documents\matflow项目\LMateLab-107Cup'
git pull --ff-only origin main
git worktree add ..\LMateLab-107Cup-frontend-preview-evidence -b codex/107cup-frontend-preview-evidence main
Set-Location '..\LMateLab-107Cup-frontend-preview-evidence'
```

Create `docs/107cup/frontend-preview-evidence.md` in this evidence worktree containing:

- merged main commit;
- local test/build commands and counts;
- before snapshot Job and evidence path;
- preview build Job, node if scheduler evidence retains it, terminal state, logs, and manifest SHA-256;
- preview service Job, node, port, start/end states, and health JSON;
- browser viewport results, canvas pixel counts, console/write-request counts, and external screenshot directory hash list;
- after snapshot Job and stable-state comparison;
- explicit statement that all data shown was demo and phase 5-8 functionality remains unimplemented.

Do not include passwords, JWTs, SSH keys, private IP whitelist secrets, or copied database contents.

- [ ] **Step 13: Update the roadmap without overstating phase status**

In the same evidence worktree, mark only the frontend-preview checklist items whose local, Slurm, browser, stop, and stable-state evidence actually passed. Keep stages 5-8 `PENDING` and preserve the separate member-identity gate. If any gate failed, leave the corresponding item unchecked and link the preserved failure artifact.

- [ ] **Step 14: Commit runtime evidence on a new documentation branch**

```powershell
Set-Location '..\LMateLab-107Cup-frontend-preview-evidence'
git add docs/107cup/implementation-plan.md docs/107cup/frontend-preview-evidence.md
git commit -m "docs(107cup): record frontend preview evidence"
git push -u origin codex/107cup-frontend-preview-evidence
```

Expected: push succeeds. Merge the evidence PR through Gitea; the evidence commit itself does not trigger a stable rebuild or restart. Do not switch the implementation worktree to `main` while another worktree owns it.

## Final Acceptance Checklist

- [ ] Five authenticated competition entries and both detail routes render and refresh from the 107 preview service.
- [ ] Demo/live mode is build-time fixed; demo mode stays visibly labelled and never issues business writes.
- [ ] Success, running, failed, parse-error, forbidden, empty, loading, and render-error states do not collapse into fake success.
- [ ] The periodic table has all 118 elements, multi-select, both match modes, clear/remove, and small-screen scrolling.
- [ ] Legacy 4090 page behavior remains behind its compatibility wrappers; no legacy mutation router is exposed by `App107Cup`.
- [ ] Existing 3Dmol, crystal detail, summary, BAND/DOS, colors, formatting, and export presentation are reused rather than duplicated.
- [ ] Desktop, compact, and mobile browser checks pass with nonblank 3D canvas pixels and no incoherent overlap or document-wide horizontal overflow.
- [ ] Preview build/service have real Slurm evidence and use a fixed protected-main merge commit.
- [ ] Preview release, databases, runtime, port, Job ID, and manifests are independent.
- [ ] Preview shutdown removes only the preview port and process.
- [ ] Stable `current`, databases, service Job, and health metadata match before/after evidence.
- [ ] Phases 5-8 remain pending; no real workflow, Slurm-control, VASP, or complete-database claim is made from demo fixtures.
