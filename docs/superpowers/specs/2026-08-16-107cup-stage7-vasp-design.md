# LMateLab 107 Cup Stage 7 VASP Design

**Date:** 2026-08-16

**Status:** Approved for implementation planning

## 1. Goal

Stage 7 adds the first real VASP execution path to the 107 Cup edition. An
Operator starts one fixed MoS2 workflow from the web application, and the 107
service automatically advances it through:

```text
relax -> SCF -> BAND
             -> DOS
```

Every stage has its own immutable attempt directory and Slurm Job ID. A stage
may advance only after both scheduler completion and scientific acceptance.
The implementation must also run one deliberate SCF non-convergence workflow
and prove that BAND and DOS never receive attempts or Job IDs.

## 2. Scope

Stage 7 includes:

- fixed MoS2 `relax`, `scf`, `band`, and `dos` execution;
- one Operator start action followed by automatic reconciliation and advance;
- VASPKIT task 103 POTCAR generation on a Slurm compute node;
- scientific acceptance, immutable file hashes, retries, cancellation, and
  restart recovery;
- one complete success workflow and one controlled SCF non-convergence
  workflow on 107;
- live workflow status, bounded logs, resource evidence, and file provenance.

Stage 7 does not include:

- BAND/DOS plotting, result bundles, or the complete VASP result database;
- Agent, machine learning, arbitrary command, arbitrary script, or arbitrary
  material support;
- the legacy VASP router or legacy database write surfaces;
- VASP execution, builds, tests, or services on the 107 login node;
- VASP execution or competition data storage on the 4090 relay.

Those result-facing features remain Stage 8 work.

## 3. Confirmed Decisions

1. The deliberate failure is a scientifically meaningful SCF
   non-convergence, not a scheduler-only failure.
2. BAND and DOS are sibling branches that both depend directly on an accepted
   SCF. They are submitted one at a time, BAND first, to avoid occupying two
   GPUs simultaneously. A BAND failure does not prevent DOS from running.
3. An Operator starts the workflow once. The 107 service automatically
   reconciles, accepts, and advances it. Manual action is required only for
   cancellation or retry after failure.
4. The implementation extends the Stage 6 ledger and reconciler while keeping
   VASP preparation and scientific acceptance in a separate policy module.
5. POTCAR is generated with `vaspkit -task 103` inside each compute-node
   attempt. Manual concatenation is not a silent fallback.

## 4. Runtime Architecture

The existing single-process FastAPI service remains the only long-running
application process. It runs as a Slurm service job on a compute node. A
bounded background coordinator periodically selects only active, owned
LMateLab attempts from the database.

### 4.1 Existing scheduler boundary

`backend/services/competition_slurm.py` remains responsible for:

- fixed argv-only `sbatch`, `squeue`, `scontrol`, and `scancel` calls;
- script allowlisting;
- exact workflow/attempt directory validation;
- JobName, comment, working-directory, and Unix-user ownership checks;
- job receipts and bounded stdout/stderr reads.

It must not parse VASP outputs or decide scientific success.

### 4.2 Existing ledger boundary

`backend/services/competition_reconcile.py` remains responsible for:

- atomic workflow, step, and attempt claims;
- submission finalization and uncertain-submission recovery;
- scheduler reconciliation, cancellation races, and restart recovery;
- scheduler evidence and database state transitions.

It invokes the fixed VASP policy only after Slurm has reached a trusted
terminal state. It must not embed VASP parsing logic.

### 4.3 VASP policy and coordinator

Create `backend/services/competition_vasp.py`. It owns:

- the four fixed stage definitions and required artifacts;
- attempt input preparation and parent-product copying;
- VASPKIT task 103 and POTCAR acceptance policy;
- scientific acceptance reports;
- dependency and next-stage decisions;
- fixed acceptance-only failure profile selection.

The coordinator uses this module together with the existing reconciler. It
must use database conditional updates so that repeated ticks, repeated HTTP
requests, or a service restart cannot submit a duplicate job.

### 4.4 Fixed Slurm runner

Create one allowlisted Stage 7 runner, `deploy/107cup/slurm/vasp-stage.slurm`.
It accepts only a fixed stage key plus canonical workflow and attempt UUIDs.
It uses:

- account `competition`;
- partition `P107-RTX5090`;
- QOS `qos_p107-rtx5090`;
- one node, one task, one RTX5090 GPU, and 16 CPUs;
- `vasp_std` from the existing VASP 6.4.2 GPU installation;
- a bounded wall-time set in the implementation plan;
- private `0700` directories and `0600` files.

The runner loads
`/home/scc/pb23030683/software/vasp.6.4.2-GPU-Cell/env-nvhpc.sh` and wraps the
VASP launch with `/usr/bin/time -v`. It preserves the VASP exit code and raw
runtime metrics. It does not decide scientific acceptance.

## 5. POTCAR Generation

Each attempt contains the already validated `POSCAR` and `POTCAR.spec`. On the
compute node the fixed runner invokes:

```text
/home/scc/pb23030683/software/vaspkit.1.5.1/bin/vaspkit -task 103
```

VASPKIT uses the existing user configuration whose PBE path is
`/home/scc/pb23030683/POTCAR/PBE`. Generation passes only when all of the
following are true:

- `POTCAR.spec` is exactly `Mo_sv` followed by `S`;
- the generated POTCAR is regular, non-empty, and inside the attempt directory;
- its TITEL sequence is exactly `PAW_PBE Mo_sv` followed by `PAW_PBE S`;
- the source component hashes and generated combined hash match the approved
  107 runtime values recorded during deployment preflight;
- the VASPKIT version banner identifies version 1.5.1.

Any mismatch fails the attempt before VASP starts. POTCAR content is never
committed to Git, returned by an API, or included in a downloadable bundle.
Only identifiers, TITEL values, sizes, and SHA-256 hashes enter the ledger.

## 6. Workflow Data Flow

### 6.1 Start and claim

An Operator-only start endpoint accepts only an owned workflow in `validated`
state. A conditional database update claims the workflow and creates the first
relax attempt. A duplicate request returns the existing state and cannot create
a second attempt or Job ID.

### 6.2 Attempt input preparation

Each attempt receives real copies of its inputs. Symbolic links and hard links
are not used. Before submission, every source file is re-read and checked
against the Stage 5 size and SHA-256 ledger.

Each attempt file row records:

- the attempt and step;
- a safe relative path;
- input or output role;
- size and SHA-256;
- source workflow/attempt/file identity when copied;
- template version and release Git commit.

### 6.3 Stage products

- Relax starts from the validated MoS2 POSCAR. An accepted `CONTCAR` becomes
  the SCF `POSCAR`.
- SCF starts fresh from the accepted final structure. Its INCAR explicitly
  avoids an implicit restart.
- BAND and DOS each copy only the accepted SCF `CHGCAR` required by
  `ICHARG=11`. Their INCAR files explicitly use `ISTART=0, ICHARG=11` so that
  a WAVECAR from a different k-point mesh cannot silently alter behavior.
- The SCF `WAVECAR` is retained and hashed as required completion evidence but
  is not copied into BAND or DOS attempts.

Every parent product is rehashed before and after copying. A mismatch blocks
submission.

### 6.4 Branch ordering

After accepted SCF, BAND is submitted first. Once BAND is terminal, DOS is
submitted whether BAND succeeded or failed, because DOS depends only on SCF.
The workflow succeeds only when all four steps succeed. If BAND fails and DOS
succeeds, the final workflow remains failed while the accepted DOS evidence is
retained.

If SCF fails, BAND and DOS become `blocked` without attempt rows, attempt
directories, or Job IDs.

## 7. Scientific Acceptance

A stage is `succeeded` only when all of these independent gates pass:

1. Slurm is explicitly `COMPLETED` with `ExitCode=0:0`.
2. The VASP process exit code is zero.
3. OUTCAR contains the normal timing/accounting termination block.
4. `vasprun.xml` is complete and parseable by the pinned Pymatgen runtime.
5. Stage-specific electronic and ionic convergence requirements pass.
6. Every required artifact is regular, non-empty, parseable where applicable,
   and registered with a verified SHA-256.

The broad legacy OUTCAR regular expressions are not reused as a success
authority. A missing, truncated, or unparseable `vasprun.xml` fails closed.

### 7.1 Required artifacts

| Stage | Required evidence |
|---|---|
| relax | `OUTCAR`, `vasprun.xml`, `OSZICAR`, parseable `CONTCAR`, electronic convergence, ionic convergence |
| scf | `OUTCAR`, `vasprun.xml`, `CHGCAR`, `WAVECAR`, electronic convergence, finite Fermi energy |
| band | `OUTCAR`, `vasprun.xml`, `EIGENVAL`, electronic convergence, fixed high-symmetry path confirmation |
| dos | `OUTCAR`, `vasprun.xml`, `DOSCAR`, electronic convergence, fixed mesh and NEDOS confirmation |

The acceptance report is canonical JSON containing individual checks, measured
values, reason codes, and hashes. A failed check can never be represented as an
empty success result.

## 8. Automatic Reconciliation

The FastAPI lifespan starts one bounded coordinator loop. Each tick:

1. selects a small bounded set of active LMateLab attempts;
2. observes only their recorded Job IDs;
3. verifies scheduler ownership;
4. updates trusted scheduler state;
5. runs scientific acceptance for trusted completed jobs;
6. atomically claims the next eligible stage;
7. submits at most one new job for that claim.

The loop has an explicit interval, command timeouts, per-tick limits, and
graceful shutdown. Shutting down the web service does not cancel VASP jobs.
After restart, receipts and the database ledger recover existing submissions
before any new submission is allowed.

`unknown`, `stale`, scheduler ownership mismatch, database write failure, or
missing evidence prevents advance. The coordinator never inspects or mutates
unrelated jobs belonging to the shared Unix account.

## 9. Deliberate Failure Workflow

The acceptance-only profile is named `scf_nonconvergence_v1`. It is a fixed,
source-controlled fixture callable only by the Stage 7 evidence harness. It is
not selectable in the web UI, accepted by public request schemas, or usable as
an arbitrary INCAR override.

The workflow runs the normal relax stage. Its SCF stage uses a fixed extremely
small EDIFF and `NELM=1`, causing VASP to run while failing electronic
convergence. The normal scientific acceptance code, not a special-case result,
must reject it.

Expected ledger state:

```text
relax: succeeded, one Job ID
scf: scientific_failed, one Job ID
band: blocked, no attempt and no Job ID
dos: blocked, no attempt and no Job ID
```

## 10. Errors, Retries, and Security

- Scheduler failure and scientific failure use distinct reason codes.
- A retry always creates a new numbered attempt; previous directories, files,
  events, and reports remain immutable.
- Cancellation remains limited to exact Stage 6 ownership evidence.
- A cancellation race is reconciled against the scheduler before final state.
- Logs returned by APIs are bounded tails. API payloads expose safe relative
  paths, not server absolute paths, POTCAR content, tracebacks, or credentials.
- File checks reject symlinks, non-regular files, path traversal, changed
  hashes, oversized metadata, and unexpected stage files used as inputs.
- Database failure after scheduler acceptance enters submission recovery and
  cannot lead to a duplicate Job.

## 11. Resource and Provenance Evidence

Each attempt records:

- workflow, step, attempt, Job ID, JobName, scheduler comment, node, partition,
  QOS, CPU and GPU request;
- Slurm raw-state summary, ExitCode, observation source, timestamp, and payload
  hash;
- VASP and VASPKIT versions;
- start, finish, elapsed time, and `/usr/bin/time -v` maximum resident set size;
- input manifest, output manifest, parent-product links, release commit, and
  acceptance report hash;
- bounded stdout and stderr evidence.

Peak RSS is explicitly process-tree evidence from the fixed launcher because
the 107 `sacct` backend is unavailable. It must not be relabeled as historical
Slurm MaxRSS or GPU memory.

## 12. Test Strategy

Implementation follows test-driven development.

### 12.1 Unit tests

Cover POTCAR identity, stage definitions, successful fixtures, missing and empty
files, truncated XML, non-convergence, wrong k points, invalid parent products,
symlinks, hash changes, and canonical acceptance reports.

### 12.2 Fake-Slurm integration tests

Cover one-time start, duplicate requests, submission uncertainty, automatic
advance, restart recovery, scheduler failure, scientific failure, BAND/DOS
branch semantics, cancellation races, stale state, database commit failure,
and rejection of unrelated jobs.

### 12.3 Deployment contract tests

Prove the Stage 7 runner has fixed resources, fixed environment paths, VASPKIT
task 103, fixed VASP executable, private modes, argument validation, and no
login-node compute behavior.

### 12.4 107 tests

1. A Slurm build job runs the complete backend, frontend, and deployment test
   suites and produces an immutable release manifest.
2. A short compute-node preflight job verifies VASPKIT task 103, POTCAR hashes,
   the VASP environment, and the allowlisted runner without starting the real
   workflow.
3. An isolated candidate service uses database copies for API and browser
   verification without submitting VASP.
4. A stable service release is activated only after health, readiness, database
   integrity, and rollback checks pass.
5. An Operator starts one complete real MoS2 workflow from the stable web UI.
6. The evidence harness starts the fixed SCF non-convergence workflow.
7. A Viewer verifies both live workflows while every mutation remains denied.

No login-node command may perform a build, test suite, service, or VASP run.

## 13. Deployment and Completion Gates

Source merge alone makes Stage 7 at most `PARTIAL`. It becomes `DONE` only when
all of the following are true:

- four independent real VASP Job IDs form one accepted success workflow;
- the controlled SCF failure has a real Job ID and BAND/DOS have none;
- all original inputs, outputs, scheduler observations, acceptance reports,
  and SHA-256 manifests are retained on 107;
- Operator and Viewer browser checks pass against live data;
- the stable service remains healthy and unrelated shared-account jobs are
  untouched;
- `docs/107cup/stage7-vasp-evidence.md` and the master implementation plan are
  updated;
- the evidence PR is merged;
- Windows `main`, Gitea `main`, and the clean read-only 107 checkout are
  synchronized to the merged commit.

Stage 8 remains pending until real BAND/DOS parsing, plots, database records,
and downloadable result bundles are separately implemented and accepted.
