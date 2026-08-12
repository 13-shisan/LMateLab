#!/bin/bash
set -euo pipefail

root=/home/scc/pb23030683/lmatelab-107cup
commit="${1:?usage: verify-preview-runtime.sh COMMIT JOB_ID running|stopped}"
job_id="${2:?usage: verify-preview-runtime.sh COMMIT JOB_ID running|stopped}"
mode="${3:?usage: verify-preview-runtime.sh COMMIT JOB_ID running|stopped}"

[[ "$commit" =~ ^[0-9a-f]{40}$ ]]
[[ "$job_id" =~ ^[0-9]+$ ]]
[[ "$mode" =~ ^(running|stopped)$ ]]

release="$root/previews/$commit"
runtime="$root/preview-runtime/$commit/$job_id"
test -d "$release"
test -d "$runtime"
test ! -L "$runtime"

recorded_job_id=$(<"$runtime/preview-service-job-id")
node=$(<"$runtime/preview-service-node")
port=$(<"$runtime/preview-service-port")
recorded_commit=$(<"$runtime/preview-service-commit")
manifest_sha256=$(<"$runtime/preview-service-manifest-sha256")

test "$recorded_job_id" = "$job_id"
test "$recorded_commit" = "$commit"
[[ "$node" =~ ^[A-Za-z0-9._-]+$ ]]
[[ "$port" =~ ^[0-9]+$ ]]
((port >= 1 && port <= 65535))
[[ "$manifest_sha256" =~ ^[0-9a-f]{64}$ ]]
test "$(cut -d ' ' -f 1 "$release/manifest.sha256")" = "$manifest_sha256"

squeue -j "$job_id" -o '%.18i %.12P %.20j %.10T %.12M %R'
scontrol show job "$job_id"
if ! sacct -j "$job_id" --format=JobID,State,ExitCode,Elapsed,NodeList; then
  printf '%s\n' 'sacct unavailable; continuing with scontrol evidence' >&2
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
expected={"job_id": job_id, "node": node, "commit": commit, "manifest_sha256": manifest_sha256, "release_kind":"preview", "data_mode":"demo"}
for key, value in expected.items():
    if payload.get(key) != value:
        raise SystemExit(f"preview health mismatch for {key}: {payload.get(key)!r} != {value!r}")
if "JWT_SECRET" in payload or "jwt_secret" in payload:
    raise SystemExit("preview health leaked JWT metadata")
PY
  curl --fail --silent --show-error "$ready_url"
  printf '\n'
else
  if curl --connect-timeout 3 --max-time 5 --fail --silent "$health_url" >/dev/null 2>&1; then
    printf 'preview endpoint remains reachable after stop: %s\n' "$health_url" >&2
    exit 1
  fi
fi

if pgrep -u "$USER" -af 'uvicorn main_107cup:app|vite|celery worker|celery beat|redis-server' >/dev/null; then
  printf '%s\n' 'unexpected LMateLab process found on the login node' >&2
  exit 1
fi
