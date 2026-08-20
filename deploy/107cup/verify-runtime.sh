#!/bin/bash
set -euo pipefail
umask 077

root="${LMATELAB_ROOT:-/home/scc/pb23030683/lmatelab-107cup}"
runtime="$root/runtime"
current="$root/current"
verify_root=

cleanup() {
  status=$?
  trap - EXIT INT TERM
  if test -n "${verify_root:-}" && test -d "$verify_root"; then
    rm -r -- "$verify_root"
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

for name in service-job-id service-node service-port service-commit service-manifest-sha256; do
  path="$runtime/$name"
  test -f "$path"
  test ! -L "$path"
  test "$(wc -c < "$path")" -le 256
done

job_id=$(<"$runtime/service-job-id")
node=$(<"$runtime/service-node")
port=$(<"$runtime/service-port")
service_commit=$(<"$runtime/service-commit")
service_manifest_sha256=$(<"$runtime/service-manifest-sha256")

[[ "$job_id" =~ ^[1-9][0-9]*$ ]]
[[ "$node" =~ ^anode[0-9]{2}$ ]]
[[ "$port" =~ ^[0-9]{4,5}$ ]]
test "$port" -ge 1024
test "$port" -le 65535
[[ "$service_commit" =~ ^[0-9a-f]{40}$ ]]
[[ "$service_manifest_sha256" =~ ^[0-9a-f]{64}$ ]]

test -L "$current"
release=$(readlink -f -- "$current")
release_name=${release##*/}
[[ "$release_name" =~ ^[0-9a-f]{40}$ ]]
test "$release" = "$root/releases/$release_name"
test -f "$release/commit.txt"
test ! -L "$release/commit.txt"
test "$(<"$release/commit.txt")" = "$release_name"
test "$service_commit" = "$release_name"
(
  cd "$release"
  sha256sum -c manifest.sha256 >/dev/null
)
release_manifest_sha256=$(cut -d ' ' -f 1 "$release/manifest.sha256")
test "$service_manifest_sha256" = "$release_manifest_sha256"

verify_root=$(mktemp -d "$runtime/verify-runtime.XXXXXX")
chmod 700 "$verify_root"

timeout 15 squeue -j "$job_id" -o '%.18i %.12P %.20j %.10T %.12M %R'
timeout 15 sacct -j "$job_id" --format=JobID,State,ExitCode,Elapsed,NodeList

probe_endpoint() {
  url=$1
  destination=$2
  curl --fail --silent --show-error \
    --connect-timeout 3 --max-time 10 \
    --output "$destination" "$url"
}

probe_endpoint "http://$node:$port/api/health/live" "$verify_root/live.json"
probe_endpoint "http://$node:$port/api/health/ready" "$verify_root/ready.json"

python3 - "$verify_root/live.json" "$verify_root/ready.json" \
  "$job_id" "$node" "$service_commit" "$service_manifest_sha256" <<'PY'
import json
import sys

live_path, ready_path, job_id, node, commit, manifest = sys.argv[1:]
with open(live_path, encoding="utf-8") as handle:
    live = json.load(handle)
with open(ready_path, encoding="utf-8") as handle:
    ready = json.load(handle)
expected = {
    "status": "ok",
    "job_id": job_id,
    "node": node,
    "commit": commit,
    "manifest_sha256": manifest,
    "release_kind": "stable",
    "data_mode": "live",
}
for key, value in expected.items():
    if live.get(key) != value:
        raise SystemExit(f"runtime identity mismatch: {key}")
if ready != {"status": "ready"}:
    raise SystemExit("runtime readiness response is invalid")
PY

public_url="${LMATELAB_VERIFY_PUBLIC_URL:-}"
if test -n "$public_url"; then
  [[ "$public_url" =~ ^https?://[^[:space:]]+$ ]]
  public_url=${public_url%/}
  probe_endpoint "$public_url/api/health/live" "$verify_root/public-live.json"
  probe_endpoint "$public_url/api/health/ready" "$verify_root/public-ready.json"
  python3 - "$verify_root/live.json" "$verify_root/ready.json" \
    "$verify_root/public-live.json" "$verify_root/public-ready.json" <<'PY'
import json
import sys

payloads = []
for path in sys.argv[1:]:
    with open(path, encoding="utf-8") as handle:
        payloads.append(json.load(handle))
if payloads[0] != payloads[2] or payloads[1] != payloads[3]:
    raise SystemExit("public gateway does not target the verified 107 runtime")
PY
fi

for database in "$root/data/db/eln.db" "$root/data/db/digests.db"; do
  test -f "$database"
  test ! -L "$database"
  if command -v sqlite3 >/dev/null 2>&1; then
    test "$(sqlite3 -readonly "$database" 'PRAGMA query_only=ON; PRAGMA integrity_check;')" = ok
  else
    python3 - "$database" <<'PY'
import sqlite3
import sys
from pathlib import Path

path = Path(sys.argv[1])
before = path.stat()
uri = path.resolve().as_uri() + "?mode=ro"
with sqlite3.connect(uri, uri=True) as connection:
    result = connection.execute("PRAGMA integrity_check;").fetchone()[0]
after = path.stat()
if result != "ok" or (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
    raise SystemExit("database integrity or identity check failed")
PY
  fi
done

if pgrep -u "$USER" -af 'uvicorn main_107cup:app|vite|celery worker|celery beat|redis-server' >/dev/null; then
  printf '%s\n' 'unexpected LMateLab process found on the login node' >&2
  exit 1
fi

printf '%s\n' \
  "verified_job_id=$job_id" \
  "verified_node=$node" \
  "verified_commit=$service_commit" \
  "verified_manifest_sha256=$service_manifest_sha256"
