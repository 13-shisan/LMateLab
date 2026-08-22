# Competition Qoder Agent Local MVP Report

Date: `2026-08-21`

Baseline: `4e79c07b198b34e54be332638868e82249357d1f`

Branch/worktree: `codex/incar-qoder-agent` at
`/Users/joo/code/107cup-qoder-agent`

This report records local-only evidence. Nothing was pushed, merged, deployed to
107/node21, or connected to a real Qoder or USTC API.

## 1. Feature Flag And Runtime Boundary

Implemented:

- Backend and frontend flags default off.
- The backend does not register Agent routes unless
  `LMATELAB_COMPETITION_AGENT_ENABLED=1`.
- The disabled frontend build omits the Agent page chunk and exposes the
  original competition navigation and protected routes.
- Production runtime policy fixes `permission_mode=dont_ask`, disables
  YOLO/auto, and exposes no built-in tools. Bash, Write, Edit, Read, Glob, and
  WebFetch are explicitly disabled.
- Real runtime fails closed without explicit network authorization, PAT, SDK,
  and a separately approved implementation step.

Evidence:

- Registration, policy, and security tests passed.
- Static scan found no scheduler/process adapter in Agent services and no PAT
  value in source, tests, deployment script, or output.

## 2. INCAR Catalog And Selection

Implemented:

- Six immutable catalog entries are available for browsing.
- Only `2d_relax`, `band_scf`, `band_nscf`, and `dos` for
  `MoS2_monolayer` are marked applicable.
- Reference-only HSE06 and phonon entries cannot enter the executable workflow.
- Catalog responses contain no paths, scheduler commands, or POTCAR data.
- The web page supports template selection and links applicable choices to the
  existing new-calculation surface.

Evidence:

- Catalog tests passed, including unknown/path-like ID rejection.
- Browser showed four applicable and two browse-only entries.

## 3. Structured Agent Runs And Mock Worker

Implemented:

- Alembic revision `107c0ffee002` adds persisted structured Agent runs.
- Runs use queued/running/succeeded/failed states and record provider, owner,
  request kind, controlled input, advisory output, approval, and timestamps.
- A bounded worker processes mock runs without reading the Qoder PAT.
- The page polls instead of using streaming, EventSource, or WebSocket.
- Agent success is displayed as `已完成`, never as scientific acceptance.

Evidence:

- Fresh and previous-head database upgrades passed without changing workflow
  rows.
- HTTP flow passed: login `200`, six templates, run creation `201`, final
  provider `mock`, status `succeeded`, approval `true`.
- Browser completed create, polling, result display, and approval with zero
  console errors or warnings.

## 4. Workflow Result Analysis Tool

Implemented:

- Result analysis accepts only a canonical workflow ID.
- The tool enforces workflow ownership before returning a summary.
- Agent input contains only workflow ID, material, template version, recorded
  workflow status, and ordered step statuses.
- Paths, parameters, raw files, Job IDs, metadata, POTCAR, and credentials are
  excluded.
- Output states that it is advisory and does not replace scientific acceptance.

Evidence:

- Ownership and sanitization tests passed.
- Another Operator's workflow returns unavailable rather than leaking its
  existence.

## 5. Operator And Viewer Authorization

Implemented:

- Only Operators can create and approve potentially costly Agent runs.
- Operators can read only their own runs.
- Viewers can read only persisted, succeeded, explicitly approved analyses.
- Viewer responses hide the Operator prompt and controlled tool input.

Evidence:

- Route tests cover disabled flag, Operator create, Viewer create rejection,
  pre-approval hiding, approval, and post-approval sanitized read.
- Complete create -> worker -> approve -> Viewer flow passed.

## 6. Virtual Slurm Boundary

Implemented and tested:

- Agent output recommends a template but contains no submit instruction.
- A separate application-owned Slurm adapter test consumes the selected fixed
  workflow step and uses a fake executor.
- The fake submission returned Job ID `73001`, used fixed `/usr/bin/sbatch`
  argv, a fixed allowlisted script, canonical workflow/attempt IDs, and
  `shell=False`.
- `agent-worker.slurm` processes only the Agent database queue. It cannot submit
  or cancel VASP jobs and contains no PAT.

Platform note:

- The full existing secure Slurm suite requires Linux anonymous sealed file
  descriptors. On macOS, submission cases fail closed with
  `submission script snapshot is unavailable`; production code was not relaxed.
  The local virtual test replaces only that Linux descriptor primitive while
  retaining fixed argv and fake execution.

## 7. Frontend And Build

Evidence:

- Frontend full suite: `132/132` passed.
- Agent frontend contracts: `3/3` passed.
- Targeted ESLint passed.
- Agent-disabled 107cup demo build passed with `1859` transformed modules and
  no `CompetitionAgent` page chunk.
- Agent-enabled 107cup live build passed with `1859` transformed modules and a
  dedicated Agent page chunk.
- Browser desktop workflow passed.
- Browser `390x844`: document and body scroll widths both exactly `390`; no
  overflowing child elements; zero console errors/warnings.

## 8. Remaining Gates

- Real `qoder-agent-sdk` is intentionally not installed or called.
- No Qoder/USTC/node21/107 network preflight was authorized or run.
- No real PAT was requested, stored, logged, or scanned into Git.
- Existing npm dependency audit reports eight high-severity findings; no
  automatic lockfile-changing remediation was applied.
- Linux Slurm build/test, real Qoder adapter implementation, cost controls,
  server credential injection, and node21 migration require separate approval.
- This local branch is not pushed and Stage 10 status remains unchanged.

## 9. Final Local Verification

The final consolidated rerun on `2026-08-21` produced:

- Backend Agent, structure builder, migration, fake Slurm, security, and
  existing workflow model contracts: `34/34` passed.
- Frontend full suite: `134/134` passed; the Agent and structure builder
  contracts are included in that total.
- Targeted ESLint, Python bytecode compilation, Bash syntax, and
  `git diff --check`: passed.
- Agent-disabled demo build and Agent-enabled live build: passed with `1860`
  transformed modules each.
- Credential-pattern scan across all files changed for this MVP: zero matches.
- Local mock preview health: `status=ok`; the queue worker is running against
  the temporary local SQLite database.

The build retains pre-existing warnings for the bundled 3Dmol `eval`, stale
Browserslist metadata, and large chunks. No dependency or lockfile changes were
made to address those unrelated warnings.

## 10. Curated Structure Builder

The Agent page now includes a six-material offline ASE catalog, bounded
supercell/layer/vacuum/strain controls, 3D preview, and a fixed VASP input ZIP.
Only `MoS2_monolayer` remains workflow-compatible and no `POTCAR` is included.

Detailed implementation and per-feature evidence are recorded in
`docs/107cup/qoder-agent-structure-builder-report.md`.

## 11. Reviewed KPOINTS To Slurm Workflow

The structure builder now supports user-entered or mock-Qoder-advised KPOINTS,
an editable verification dialog, and handoff through the existing application
workflow coordinator. Reviewed meshes are hashed and materialized for relax,
SCF, and DOS; BAND remains the fixed high-symmetry line path. The Agent retains
no scheduler authority, and only the existing MoS2 four-step workflow can reach
the queue boundary.

## 12. Main Integration Verification

Verified on `2026-08-22` after merging `origin/main` at
`70ad7cb20b9e8ede751256f3b173f4e266f27a9a`:

- the Stage 10 recovery, evidence, and acceptance changes remain present;
- the public four-season competition homepage and protected Agent route coexist;
- focused Agent/workflow contracts passed `70/70`;
- Agent discovery tests, including migration, feature registration, security,
  structures, and fake Slurm, passed `29/29`;
- existing VASP scientific acceptance passed `100/100`;
- the complete frontend suite passed `142/142`;
- targeted Agent ESLint and the Agent-enabled 107cup production build passed
  with `1867` transformed modules;
- `git diff --check` passed and no real Qoder provider, remote scheduler, or
  server was contacted.

The real Qoder SDK, PAT injection, provider network access, and Linux Slurm
submission remain explicit post-MVP gates. The feature flag still defaults off.
