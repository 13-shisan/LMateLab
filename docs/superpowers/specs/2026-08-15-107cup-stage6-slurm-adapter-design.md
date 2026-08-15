# 107 Cup Stage 6 Slurm Adapter Design

## 1. Goal

Build the smallest production-shaped Slurm control boundary needed by the fixed
107 Cup workflow. Stage 6 submits and observes ordinary probe jobs only. It does
not run VASP, advance `relax -> SCF -> BAND -> DOS`, parse results, or add Agent
features.

The adapter must run from a Slurm compute-node service, survive a fresh process
reading the same database, and refuse to cancel any job that cannot be proven to
belong to the exact LMateLab workflow attempt.

## 2. Verified Platform Facts

The design is based on a live probe from stable service Job `37715` on
`anode02` on 2026-08-15:

- `sbatch --test-only` succeeds from the compute allocation. Its reported test
  ID `38285` was not present in `squeue`, so the probe created no job.
- `squeue`, `scontrol --json`, and `squeue --json` work from the compute node.
- `scancel` is available from Slurm `25.11.2`; a real cancellation is deferred
  to the owned Stage 6 smoke job.
- `sacct` fails because the configured accounting service at
  `localhost:6819` refuses the connection.

Therefore live `squeue/scontrol` data is authoritative while a job is retained
by `slurmctld`. `sacct` is queried for final accounting when available. If
neither source can prove a final state, reconciliation records `unknown` with a
stale timestamp; it never leaves a missing job displayed as running and never
guesses success.

## 3. Scope

In scope:

- fixed absolute Slurm binaries invoked with argument arrays and bounded
  timeouts;
- structured JSON parsing for `squeue` and `scontrol`, with raw scheduler state,
  exit code, reason, source, node and observation time retained;
- one database-backed `WorkflowAttempt` ledger entry per submission;
- strict working-directory and log containment;
- fail-closed ownership verification before `scancel`;
- restart-safe reconciliation from the database plus scheduler evidence;
- Operator cancellation API and read-only attempt evidence in workflow detail;
- a fixed ordinary probe script for success, deliberate failure and cancellation
  acceptance tests.

Out of scope:

- VASP execution or POTCAR assembly;
- dependency submission for the four scientific steps;
- automatic retry, priority changes, requeue, hold/release or arbitrary Slurm
  options;
- arbitrary script paths, commands, partitions, accounts, QOS values or resource
  requests from HTTP input;
- cancellation based only on the shared Linux account.

## 4. Architecture

### 4.1 Slurm client

`backend/services/competition_slurm.py` owns the process boundary. A small
injectable runner executes only configured absolute binaries such as
`/usr/bin/sbatch`, `/usr/bin/squeue`, `/usr/bin/scontrol`, `/usr/bin/sacct` and
`/usr/bin/scancel`. Calls use `subprocess.run(argv, shell=False, ...)`, UTF-8
decoding with replacement, output limits and per-command timeouts.

The client exposes typed operations for test-only submission, real submission,
job observation, cancellation and bounded log reads. HTTP values never become
binary paths, script paths, environment variable names or raw Slurm options.

### 4.2 Submission ledger

`backend/services/competition_reconcile.py` owns database transitions. Before
calling `sbatch`, it claims one validated workflow step and commits an attempt in
`submitting` state with a private attempt directory. The submitted job receives:

```text
JobName: lmatelab-<short workflow id>-<step>-a<number>
WorkDir: <workflow root>/<workflow id>/attempts/<attempt id>
Comment: lmatelab:workflow=<workflow id>;attempt=<attempt id>
StdOut:  <attempt directory>/stdout.log
StdErr:  <attempt directory>/stderr.log
```

After `sbatch --parsable`, the Job ID is written atomically to a private receipt
before the database row is updated. A fresh process can recover a submission
that stopped between scheduler acceptance and the database update by matching
the ledger attempt ID against the exact scheduler comment and working directory.

Stage 6 exposes this submission primitive only to the fixed smoke harness. The
public scientific workflow start remains Stage 7, when the fixed VASP stage
script exists.

### 4.3 Ownership and cancellation

Cancellation requires all of the following at the moment immediately before
`scancel`:

1. scheduler JobName starts with `lmatelab-`;
2. scheduler WorkDir is inside the configured workflow root and equals the
   ledger attempt directory;
3. scheduler comment exactly names the workflow ID and attempt ID;
4. the same database attempt stores the same Job ID.

The scheduler user is also checked against the configured 107 account when the
field is available. Any missing, malformed, stale or mismatched field rejects
cancellation. The shared account is never sufficient evidence.

### 4.4 Reconciliation and API

The reconciler maps Slurm states to the existing workflow states while retaining
the raw state. Active attempts are refreshed from `squeue/scontrol`; terminal
accounting is enriched from `sacct` when it works. Scheduler failure records an
explicit observation error and stale timestamp.

Workflow detail returns the latest attempt for each step, including Job ID,
attempt number, relative attempt directory, raw Slurm state, exit code and
reason. An Operator can cancel only an owned active attempt. Viewer remains
read-only. No endpoint accepts a Job ID as authority by itself.

## 5. Failure Handling

- Command timeout: return a typed unavailable result; preserve stderr in
  sanitized evidence and do not change to a terminal success/failure state.
- Malformed JSON or unexpected state: preserve the raw payload hash and record
  `unknown` rather than guessing.
- `sbatch` failure before Job ID: mark the attempt `submission_failed` and retain
  the attempt directory.
- Job ID received but database update fails: preserve the receipt and recover by
  exact comment/workdir matching; cancellation uses the full ownership gate.
- `sacct` unavailable: continue live observation through `squeue/scontrol`, then
  fail closed to `unknown/stale` if no authoritative final record remains.
- Log access: reject absolute paths, traversal and symlinks; return at most the
  configured tail byte count.

## 6. Verification

Local fake-Slurm tests cover argument construction, timeout, malformed output,
all state classes, bounded log reads, submission recovery, four-part ownership,
cancellation races and restart reconciliation.

After merge, 107 validation runs only through Slurm compute jobs and retains
Job IDs, raw scheduler JSON/text, stdout/stderr, database state and SHA-256
manifests for:

1. `sbatch --test-only` with no residual job;
2. one successful ordinary probe;
3. one deliberately failed probe;
4. one running probe cancelled through the adapter;
5. one non-LMateLab probe that the adapter refuses to cancel, followed by
   operator-owned cleanup outside the adapter;
6. a fresh Python process reconciling the same ledger and active/final jobs.

Stage 6 is complete only after the merged commit passes local tests, a 107 Slurm
build, the real smoke matrix, evidence review and a separate evidence PR.
