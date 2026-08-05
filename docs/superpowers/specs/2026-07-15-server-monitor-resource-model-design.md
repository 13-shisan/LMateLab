# Server Monitor Resource Model and Collection Design

Date: 2026-07-15

## 1. Purpose

Rebuild the server monitor around three distinct concepts:

1. A physical server or cluster owns resource capacity and scheduler state.
2. A login account is an access and collection identity under a physical server.
3. A lab member is a canonical person or lab account with platform-specific scheduler aliases.

The design must keep resource availability accurate even when external-group users are hidden, avoid double-counting shared scheduler snapshots, retain visibility into every configured login account, and reduce the manual work required for isolated or MFA-protected platforms.

## 2. Confirmed Decisions

- Use a strict lab-member allowlist. Unknown scheduler usernames are external by default.
- External identities are not returned by the API or rendered in the UI.
- External resource use remains part of physical-server capacity and total-load metrics.
- Physical-server resources and jobs are counted once even when multiple login accounts collect the same cluster-wide snapshot.
- Login accounts remain individually visible with collection mode, latest update, and health state.
- Use the compact operations-board layout for `/dashboard/server-monitor`.
- Use a member worktable for `/dashboard/server-monitor/users-overview`.
- Use larger production typography: page titles about 24-26 px, member names 15-16 px, body and controls 13-14 px, and primary metrics 22-26 px.
- Desktop and mobile are separate responsive layouts. The mobile preview is not rendered inside the desktop page.

## 3. Physical Server and Account Catalog

The catalog is stored as structured JSON and validated by Pydantic when the backend starts. It contains no passwords, private keys, MFA seeds, or bearer tokens.

The confirmed multi-account groups are:

| Physical server ID | Display name | Login account IDs | Legacy source directories |
| --- | --- | --- | --- |
| `shuangyiliu-hfnl` | 双一流微尺度 | `xjwu`, `hflv`, `wjb` | `Shuangyiliu-HFNL-xjwu`, `Shuangyiliu-HFNL-hflv`, and a new source for `wjb@114.214.207.167` |
| `dongfang` | 东方超算 | `xjwu`, `yang4` | `Dongfang-xjwu`, `Dongfang-yang4` |
| `jingzhun` | 精准平台 | `xjwu`, `jbwu` | `Jingzhun-xjwu`, `Jingzhun-jbwu` |

`Jingzhun-GPU` remains a separate physical resource named 精准平台 GPU. It is not merged into the 精准平台 CPU cluster.

Every other legacy source initially maps one-to-one to a physical server. The catalog supports adding accounts later without frontend, aggregation, or synchronization code changes.

Each account entry includes:

- stable account ID;
- login username and host, when safe to record;
- legacy source directory;
- collection mode: `node21_pull`, `windows_relay`, or `manual_upload`;
- expected collection interval and stale threshold;
- deterministic snapshot priority for shared physical servers;
- enabled and setup state.

## 4. Lab Member Registry

The member registry is also structured JSON and validated at startup. It is seeded from the previously confirmed dataset accounts:

`Pwjb`, `Pwjx`, `Pwxm`, `ies`, `Pchenxj`, `Pgaoyan`, `Pjzh`, `Plyf`, `Psunmiao`, `Pxpb`, `Pbpf`, `Pcheyx`, `Pgyh`, `Pwyt`, `Plfx`, `Psxz`, `Pzhangka`, `Pzxp`, `Pcato`, `Pcxy`, `Phflv`, `Pliyuxuan`, `Pwangdy`, `Pwyl`, `Pzzy`, `Pczp`, `Pjyq`, and `Pluoxiao`.

Existing valid aliases migrate into the registry, including case-insensitive forms such as `Plyf/lyf`, `Pwjb/wjb`, `Pzhangka/Pzhangkai`, `Psunmiao/sunmiao`, and `Pbpf/bpf`. `zhangwh`, `whzhang`, `qxli`, `bli`, and `bcpan` are not allowlisted. Any other unregistered username is treated as external automatically.

Each member has a canonical ID, display name, and aliases. A display name that has not been verified uses the canonical account ID rather than an inferred Chinese name.

## 5. Snapshot Contract and Compatibility

New snapshots use a versioned wrapper:

```json
{
  "schema_version": 2,
  "collector_version": "...",
  "physical_server_id": "shuangyiliu-hfnl",
  "account_id": "wjb",
  "source_id": "shuangyiliu-hfnl-wjb",
  "collected_at": "2026-07-15T12:00:00+08:00",
  "payload": {}
}
```

The existing `status.json` and history directories remain readable through a legacy adapter. Initial deployment is non-destructive and does not rename or delete historical artifacts.

Normalized version-2 history removes external usernames, job names, work directories, and command details. It retains anonymous state, queue, node, and resource occupancy information required for accurate total-load metrics. Legacy raw artifacts remain server-filesystem-only and are never exposed by the API.

## 6. Resource and User Statistical Scopes

### 6.1 Physical-server scope

Physical-server metrics answer: "What resources are actually available now?"

- Node totals and busy/free/down counts come directly from Slurm or PBS node state.
- GPU occupancy comes from complete GPU/process state before identity filtering.
- CPU, memory, disk, queue depth, running-job count, and pending-job count include all workloads.
- External usernames are omitted, but their workload remains in anonymous total-load counts.

The implementation must never calculate free nodes as `total nodes - lab occupied nodes`. If external users occupy two nodes, those nodes remain busy.

### 6.2 Lab-member scope

Lab-member metrics answer: "How is the lab using the available systems?"

- Active member, lab running-job, lab queued-job, and lab history counts include allowlisted aliases only.
- Physical-server coverage is counted by physical server, not by login account.
- External users do not appear in API filters, rows, exports, or cached overview payloads.

### 6.3 Account scope

A login account represents access and collection status. A collector running as `xjwu`, `hflv`, or `wjb` may see the same cluster-wide queue. Therefore:

- account cards show setup state, collection mode, freshness, and last successful synchronization;
- physical resources and scheduler jobs are not assigned to the collector account merely because that account produced the snapshot;
- a member-to-account relationship is shown only when scheduler or accounting metadata proves it reliably;
- otherwise a member is associated only with the physical server, while accounts are listed separately under that server.

## 7. Shared Snapshot Selection and Deduplication

For each physical server, the backend selects one resource-truth snapshot:

1. discard invalid, future-dated, or incompatible snapshots;
2. prefer snapshots inside the configured freshness window;
3. select the newest collected timestamp;
4. break ties with catalog snapshot priority.

Snapshots from sibling accounts are not summed or unioned. If valid sibling snapshots for the same time window materially disagree on hostname, scheduler type, node totals, or job-set fingerprint, the server is marked `inconsistent` and the newest deterministic candidate remains visible with a warning.

Historical aggregation selects one physical-server snapshot per configured time bucket. Job identity is keyed by physical server plus scheduler job ID, preventing collisions across clusters.

## 8. Collection Architecture

### 8.1 Node21 automatic pull

Reachable sources continue to be pulled by node21. The pull script is generated from the catalog and adds:

- `flock` to prevent overlap;
- connection and transfer timeouts;
- per-source staging directories and atomic replacement;
- independent exit status and last-error metadata;
- per-source logs with rotation instead of one unbounded `sync.log`;
- no wildcard copy into another source's directory.

The new `wjb@114.214.207.167` source receives the canonical collector, a remote cron entry, a local source directory, and node21 pull configuration.

### 8.2 Windows interactive relay

For 精准平台 GPU, 合肥超算, 无锡超算, and 东方超算 sources that cannot be pulled from node21, a PowerShell relay runs on the user's Windows machine:

1. perform an SSH preflight for the configured source;
2. prompt interactively for the dynamic password or MFA challenge;
3. execute or retrieve the versioned collector snapshot;
4. validate the snapshot locally;
5. upload it to MatFlow over HTTPS;
6. remove temporary local material after a confirmed upload.

The relay does not store remote passwords, private keys, or MFA seeds. A source-scoped MatFlow ingestion token is stored through Windows Credential Manager rather than in the repository or script. If Windows OpenSSH cannot reach a platform, the relay reports the failed stage without modifying the last valid server snapshot.

### 8.3 Browser upload fallback

An authenticated upload action accepts a single snapshot file for a catalog account. It is a fallback for platforms that require a special client or cannot be reached through Windows OpenSSH. It replaces manual directory copying but remains explicitly labeled as a manual update.

## 9. Ingestion Security and Failure Handling

- Ingestion is allowlisted by physical server, account, and source ID.
- Relay tokens are source-scoped, hashed at rest, revocable, and excluded from Git.
- Browser uploads use the existing authenticated session and an explicit server-monitor permission.
- Payloads have strict content type, size, schema, timestamp-skew, and source-identity checks.
- File paths are derived from catalog IDs, never from unchecked request paths.
- Valid snapshots are written through a temporary file and `os.replace` while holding a lock.
- Invalid or failed updates never overwrite the last valid snapshot.
- Every ingest records source, time, outcome, checksum, and error class without recording credentials.

Account health states are `normal`, `delayed`, `stale`, `pending_setup`, `connection_failed`, `invalid_snapshot`, and `inconsistent`. Thresholds are defined per source because automatic and manual sources have different expected intervals.

## 10. API Design

The server list API returns physical servers with nested account status and two metric scopes:

- `resource_summary`: complete physical resource and anonymous total load;
- `lab_summary`: allowlisted users and jobs only.

The users overview API returns only canonical lab members, physical-server coverage, and reliable account attribution. Cache keys include range and catalog/member-registry versions. Snapshot ingestion and registry changes invalidate the affected overview cache ranges.

Legacy source routes redirect to or resolve through the new physical server ID so existing bookmarked URLs continue to work.

## 11. Frontend Design

### 11.1 Server monitor entry

- Replace the large hero and repeated cards with a compact operations board.
- Show total physical servers, configured accounts, automatic sources, and sources requiring attention.
- Separate current sources from stale/manual sources.
- Each physical-server row shows resource truth, anonymous total load, lab load, freshness, and expandable account chips.
- Account chips show status but do not duplicate physical resource metrics.

### 11.2 Users overview

- Use a table-first member workbench rather than repeated user cards plus a second matrix.
- Filters cover range, physical server, login account when attribution is reliable, member, and freshness.
- Tabs provide member list, physical-server coverage, and historical trend views.
- Desktop retains complete columns; mobile renders full-width member rows with expandable details.
- The strict allowlist is a fixed scope indicator, not an optional "all scheduler users" filter.

## 12. Performance and Retention

- Retain stale-while-refresh overview caches and atomic cache writes.
- Group history by physical server before aggregation to avoid duplicate account scans.
- Ingestion refreshes only affected cache ranges asynchronously.
- Add log rotation for pull and relay logs.
- Preserve existing history during migration; any future retention deletion requires a separate reviewed change.

## 13. Testing and Acceptance

Required automated coverage includes:

- catalog validation and exact multi-account grouping;
- allowlist and alias normalization;
- unknown/external usernames absent from API output;
- external workloads retained in total queue and resource metrics;
- regression fixture where external users occupy two nodes and free-node count remains scheduler-accurate;
- three sibling snapshots for 双一流微尺度 count physical resources once;
- conflicting sibling snapshots produce `inconsistent` without summing;
- login accounts remain visible when a source is missing or pending setup;
- upload authentication, source scoping, path traversal, payload size, invalid JSON, future timestamp, and atomic write behavior;
- cache invalidation and legacy route compatibility;
- desktop and 390 px mobile layout, larger typography, filters, account expansion, stale state, empty state, and error state;
- Windows relay preflight, user cancellation, failed authentication, failed upload, retry, and temporary-file cleanup.

Production acceptance requires fresh container health, public health endpoints, authenticated browser checks for both routes, desktop and mobile screenshots, no relevant console errors, and explicit verification of all three confirmed multi-account groups.

## 14. Migration and Rollback

1. Add validated catalog and member registry while retaining legacy source IDs.
2. Add backend grouping, filtering, deduplication, and tests.
3. Add versioned ingestion and Windows relay without changing existing pulls.
4. Install and validate the new 双一流微尺度 `wjb` collector.
5. Replace the generated node21 pull job after a dry run.
6. Deploy the frontend after API compatibility tests pass.
7. Prewarm overview caches and run browser acceptance.

Rollback restores the previous backend/frontend images and existing `sync_all.sh`. Legacy artifacts remain untouched, so rollback does not require data conversion.

## 15. Non-goals

- Bypassing MFA, dynamic-password, VPN, or network-isolation controls.
- Inferring task ownership from the account that collected a global scheduler snapshot.
- Replacing Slurm/PBS accounting with a new monitoring database.
- Deleting existing historical artifacts in this change.
- Exposing external-group identities to administrators through the normal dashboard API.
