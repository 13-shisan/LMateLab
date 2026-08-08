#!/bin/bash
#SBATCH --job-name=lmatelab-provision-viewer
#SBATCH --account=competition
#SBATCH --partition=P107-A100
#SBATCH --qos=qos_p107-a100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/provision-viewer-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/provision-viewer-%j.err

set -euo pipefail
umask 077

: "${SLURM_JOB_ID:?provision-viewer.slurm must run through Slurm}"

root=/home/scc/pb23030683/lmatelab-107cup
project=/home/scc/pb23030683/projects/LMateLab-107Cup
python_env="$root/envs/python"
provisioner="${LMATELAB_VIEWER_PROVISIONER:-$project/deploy/107cup/provision-competition-viewer.py}"
source_commit="${LMATELAB_VIEWER_SOURCE_COMMIT:-$(git -C "$project" rev-parse HEAD)}"
credentials_dir="$root/config/credentials"
password_file="$credentials_dir/demo-viewer.password"
evidence_root="$root/evidence/access/viewer-$SLURM_JOB_ID"
evidence_manifest="$root/evidence/access/viewer-$SLURM_JOB_ID.manifest.sha256"
database="$root/data/db/eln.db"
backup_dir="$root/backups/competition-viewer"

[[ "$source_commit" =~ ^[0-9a-f]{40}$ ]]
test -x "$python_env/bin/python"
test -f "$provisioner"
test -f "$database"
test ! -e "$evidence_root"
test ! -e "$evidence_manifest"

mkdir -p "$root/logs" "$root/evidence/access" "$credentials_dir"
chmod 0700 "$root/evidence/access" "$credentials_dir"
mkdir "$evidence_root"
chmod 0700 "$evidence_root"

if ! test -e "$password_file" && ! test -L "$password_file"; then
  "$python_env/bin/python" - "$password_file" <<'PY'
import os
import secrets
import sys

path = sys.argv[1]
file_descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(file_descriptor, "w", encoding="utf-8") as handle:
    handle.write(secrets.token_urlsafe(32) + "\n")
PY
fi

test -f "$password_file"
test ! -L "$password_file"
test "$(stat -c %a "$password_file")" = 600
test "$(stat -c %U "$password_file")" = "$USER"

"$python_env/bin/python" "$provisioner" \
  --database "$database" \
  --backup-dir "$backup_dir" \
  --password-file "$password_file" \
  --email demo-viewer@matflow.top \
  --name "107 Cup Demo Viewer" \
  --alias demo-viewer \
  > "$evidence_root/provision-result.json"

"$python_env/bin/python" - "$database" \
  > "$evidence_root/viewer-row.txt" <<'PY'
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as connection:
    rows = connection.execute(
        "SELECT id, email, alias, role FROM users WHERE alias = ?",
        ("demo-viewer",),
    ).fetchall()
    integrity = connection.execute("PRAGMA integrity_check;").fetchone()[0]
assert len(rows) == 1, rows
assert rows[0][1:] == ("demo-viewer@matflow.top", "demo-viewer", "viewer"), rows
assert integrity == "ok", integrity
print(f"id={rows[0][0]} email={rows[0][1]} alias={rows[0][2]} role={rows[0][3]}")
print(f"integrity_check={integrity}")
PY

service_job_id=$(<"$root/runtime/service-job-id")
service_node=$(<"$root/runtime/service-node")
service_port=$(<"$root/runtime/service-port")
curl --fail --silent --show-error \
  "http://$service_node:$service_port/api/health/ready" \
  > "$evidence_root/service-ready.json"

printf '%s\n' \
  "job_id=$SLURM_JOB_ID" \
  "node=${SLURMD_NODENAME:-$(hostname)}" \
  "source_commit=$source_commit" \
  "viewer_alias=demo-viewer" \
  "viewer_role=viewer" \
  "service_job_id=$service_job_id" \
  "production_current=$(readlink -f "$root/current")" \
  "completed_at=$(date --iso-8601=seconds)" \
  > "$evidence_root/SUCCESS.txt"

chmod 0600 "$evidence_root"/*
find "$evidence_root" -type f -print0 | sort -z | xargs -0 sha256sum \
  > "$evidence_manifest"
chmod 0600 "$evidence_manifest"
sha256sum -c "$evidence_manifest" >/dev/null
