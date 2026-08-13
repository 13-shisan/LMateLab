#!/bin/bash
set -euo pipefail

root=/home/scc/pb23030683/lmatelab-107cup
commit="${1:?usage: verify-workflow-preview-runtime.sh COMMIT JOB_ID running|stopped}"
job_id="${2:?usage: verify-workflow-preview-runtime.sh COMMIT JOB_ID running|stopped}"
mode="${3:?usage: verify-workflow-preview-runtime.sh COMMIT JOB_ID running|stopped}"

[[ "$commit" =~ ^[0-9a-f]{40}$ ]]
[[ "$job_id" =~ ^[0-9]+$ ]]
[[ "$mode" =~ ^(running|stopped)$ ]]

release="$root/workflow-previews/$commit"
runtime="$root/workflow-preview-runtime/$commit/$job_id"
test -d "$release"
test -d "$runtime"
test ! -L "$runtime"

recorded_job_id=$(<"$runtime/workflow-preview-service-job-id")
node=$(<"$runtime/workflow-preview-service-node")
port=$(<"$runtime/workflow-preview-service-port")
recorded_commit=$(<"$runtime/workflow-preview-service-commit")
manifest_sha256=$(<"$runtime/workflow-preview-service-manifest-sha256")

test "$recorded_job_id" = "$job_id"
test "$recorded_commit" = "$commit"
[[ "$node" =~ ^[A-Za-z0-9._-]+$ ]]
[[ "$port" =~ ^[0-9]+$ ]]
((port >= 1 && port <= 65535))
[[ "$manifest_sha256" =~ ^[0-9a-f]{64}$ ]]
test "$(cut -d ' ' -f 1 "$release/manifest.sha256")" = "$manifest_sha256"
test -s "$runtime/schema-evidence.json"
test -s "$runtime/acceptance-credentials.json"
test "$(stat -c '%a' "$runtime/schema-evidence.json")" = 600
test "$(stat -c '%a' "$runtime/acceptance-credentials.json")" = 600
grep -q '"revision": "107c0ffee001"' "$runtime/schema-evidence.json"
grep -q '"workflow_runs"' "$runtime/schema-evidence.json"
grep -q '"workflow_steps"' "$runtime/schema-evidence.json"
grep -q '"workflow_attempts"' "$runtime/schema-evidence.json"
grep -q '"workflow_events"' "$runtime/schema-evidence.json"
grep -q '"workflow_files"' "$runtime/schema-evidence.json"
grep -q '"workflow_templates"' "$runtime/schema-evidence.json"

squeue_output=$(squeue -h -j "$job_id" -o '%i|%T')
printf '%s\n' "$squeue_output"
if test "$mode" = running; then
  test -n "$squeue_output"
else
  test -z "$squeue_output"
fi

scontrol_output=""
if ! scontrol_output=$(scontrol show job "$job_id"); then
  if test "$mode" = running; then
    exit 1
  fi
  printf '%s\n' 'scontrol record unavailable after preview stop; continuing with runtime evidence' >&2
else
  printf '%s\n' "$scontrol_output"
  if test "$mode" = stopped; then
    scontrol_state=$(sed -n 's/.* JobState=\([^ ]*\).*/\1/p' <<<"$scontrol_output" | head -n 1)
    case "$scontrol_state" in
      BOOT_FAIL|CANCELLED*|COMPLETED|DEADLINE|FAILED|NODE_FAIL|OUT_OF_MEMORY|PREEMPTED|REVOKED|SPECIAL_EXIT|TIMEOUT) ;;
      *)
        printf 'workflow preview has non-terminal scontrol state after stop: %s\n' "$scontrol_state" >&2
        exit 1
        ;;
    esac
  fi
fi
sacct_output=""
if ! sacct_output=$(sacct -nP -j "$job_id" --format=JobIDRaw,State,ExitCode,Elapsed,NodeList); then
  printf '%s\n' 'sacct unavailable; continuing with runtime evidence' >&2
else
  printf '%s\n' "$sacct_output"
  if test "$mode" = stopped && test -n "$sacct_output"; then
    sacct_state=$(awk -F '|' -v job="$job_id" '$1 == job { print $2; exit }' <<<"$sacct_output")
    case "$sacct_state" in
      BOOT_FAIL|CANCELLED*|COMPLETED|DEADLINE|FAILED|NODE_FAIL|OUT_OF_MEMORY|PREEMPTED|REVOKED|SPECIAL_EXIT|TIMEOUT) ;;
      *)
        printf 'workflow preview has missing or non-terminal sacct state after stop: %s\n' "$sacct_state" >&2
        exit 1
        ;;
    esac
  fi
fi
(cd "$release" && sha256sum -c manifest.sha256 && sha256sum -c manifest.txt)

health_url="http://$node:$port/api/health/live"
ready_url="http://$node:$port/api/health/ready"

if test "$mode" = running; then
  health_json=$(curl --fail --silent --show-error "$health_url")
  printf '%s\n' "$health_json"
  HEALTH_JSON="$health_json" python3 - "$job_id" "$node" "$commit" "$manifest_sha256" <<'PY'
import json
import os
import sys

job_id, node, commit, manifest_sha256 = sys.argv[1:]
payload = json.loads(os.environ["HEALTH_JSON"])
expected = {
    "job_id": job_id,
    "node": node,
    "commit": commit,
    "manifest_sha256": manifest_sha256,
    "release_kind": "preview",
    "data_mode": "live",
}
for key, value in expected.items():
    if payload.get(key) != value:
        raise SystemExit(f"workflow preview health mismatch for {key}: {payload.get(key)!r} != {value!r}")
if "JWT_SECRET" in payload or "jwt_secret" in payload:
    raise SystemExit("workflow preview health leaked JWT metadata")
PY
  curl --fail --silent --show-error "$ready_url"
  printf '\n'
else
  if curl --connect-timeout 3 --max-time 5 --fail --silent "$health_url" >/dev/null 2>&1; then
    printf 'workflow preview endpoint remains reachable after stop: %s\n' "$health_url" >&2
    exit 1
  fi
fi

if pgrep -u "$USER" -af 'uvicorn main_107cup:app|vite|celery worker|celery beat|redis-server' >/dev/null; then
  printf '%s\n' 'unexpected LMateLab process found on the login node' >&2
  exit 1
fi
