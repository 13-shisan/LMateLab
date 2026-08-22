# Competition Qoder Agent Local MVP Plan

**Baseline:** `4e79c07b198b34e54be332638868e82249357d1f`

**Scope:** Build an isolated, default-off competition Agent surface. The first
local release uses only a deterministic mock provider and fake Slurm fixtures.
It does not connect to Qoder, USTC APIs, 107, or node21.

## Contracts

1. `LMATELAB_COMPETITION_AGENT_ENABLED` defaults to `0`; disabled routes fail
   closed without changing existing competition behavior.
2. Only Operators can create or approve Agent runs. Viewers can read only
   approved, persisted runs.
3. Agent inputs contain template IDs and workflow IDs, never paths, POTCAR,
   credentials, raw files, scheduler commands, or another Operator's data.
4. `MoS2_monolayer` with `2d_relax`, `band_scf`, `band_nscf`, and `dos` is the
   only executable catalog surface. Other templates are browse/export only.
5. Qoder built-in Bash/Write/Edit/Read/Glob/WebFetch tools are unavailable.
   Production configuration is `permission_mode=dont_ask`; YOLO/auto is off.
6. Agent output is advisory. It cannot submit/cancel Slurm, mutate attempts,
   advance workflows, or decide scientific success.

## Delivery Steps

- [ ] Add failing backend contracts for catalog, runtime, tools, persistence,
      authorization, feature flag, and worker deployment.
- [ ] Add failing frontend contracts for navigation, polling, role boundaries,
      template selection, and approved analysis display.
- [ ] Implement structured models/schemas and an Alembic migration.
- [ ] Implement catalog, sanitized workflow tools, mock runtime, service, API,
      and one-shot worker.
- [ ] Implement the compact Agent page and provider methods.
- [ ] Run fake Slurm regression without allowing Agent code to invoke Slurm.
- [ ] Run focused suites, related regression, frontend build, diff check, and
      secret/static safety scans.
- [ ] Record one report section per feature and run a local browser preview.
