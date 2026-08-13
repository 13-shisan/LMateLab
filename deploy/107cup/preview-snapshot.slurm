#!/bin/bash
#SBATCH --job-name=lmatelab-preview-snapshot
#SBATCH --account=competition
#SBATCH --partition=P107-A100
#SBATCH --qos=qos_p107-a100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/preview-snapshot-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/preview-snapshot-%j.err

set -euo pipefail
umask 077

: "${SLURM_JOB_ID:?preview-snapshot.slurm must run through Slurm}"
: "${LMATELAB_PREVIEW_COMMIT:?preview commit is required}"
: "${LMATELAB_PREVIEW_SNAPSHOT_PHASE:?snapshot phase is required}"

commit="$LMATELAB_PREVIEW_COMMIT"
phase="$LMATELAB_PREVIEW_SNAPSHOT_PHASE"
root=/home/scc/pb23030683/lmatelab-107cup

[[ "$commit" =~ ^[0-9a-f]{40}$ ]]
[[ "$phase" =~ ^(before|after)$ ]]

evidence_parent="$root/evidence/previews/$commit"
evidence="$evidence_parent/$phase-$SLURM_JOB_ID"
mkdir -p "$evidence_parent"
test ! -e "$evidence"
mkdir "$evidence"
chmod 700 "$evidence"

test -L "$root/current"
readlink -f "$root/current" > "$evidence/current-target.txt"

for database_name in eln digests; do
  database="$root/data/db/$database_name.db"
  test -f "$database"
  sha256sum "$database" | cut -d ' ' -f 1 > "$evidence/stable-$database_name.sha256"
  python3 - "$database" > "$evidence/stable-$database_name-integrity.txt" <<'PY'
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

path = Path(sys.argv[1]).resolve()
uri = f"file:{quote(str(path))}?mode=ro&immutable=1"
connection = sqlite3.connect(uri, uri=True)
try:
    print(connection.execute("PRAGMA integrity_check").fetchone()[0])
finally:
    connection.close()
PY
  test "$(<"$evidence/stable-$database_name-integrity.txt")" = ok
done

for field in job-id node port commit; do
  source_file="$root/runtime/service-$field"
  test -f "$source_file"
  cp "$source_file" "$evidence/stable-service-$field.txt"
done

stable_job_id=$(<"$evidence/stable-service-job-id.txt")
stable_node=$(<"$evidence/stable-service-node.txt")
stable_port=$(<"$evidence/stable-service-port.txt")
[[ "$stable_job_id" =~ ^[0-9]+$ ]]
[[ "$stable_node" =~ ^[A-Za-z0-9._-]+$ ]]
[[ "$stable_port" =~ ^[0-9]+$ ]]
((stable_port >= 1 && stable_port <= 65535))

curl --fail --silent --show-error \
  "http://$stable_node:$stable_port/api/health/live" \
  > "$evidence/stable-health-live.json"
squeue -j "$stable_job_id" -o '%.18i %.12P %.20j %.10T %.12M %R' > "$evidence/squeue.txt"
scontrol show job "$stable_job_id" > "$evidence/scontrol.txt"
if ! sacct -j "$stable_job_id" --format=JobID,State,ExitCode,Elapsed,NodeList \
  > "$evidence/sacct.txt" 2> "$evidence/sacct.stderr.txt"; then
  printf '%s\n' unavailable > "$evidence/sacct-status.txt"
else
  printf '%s\n' available > "$evidence/sacct-status.txt"
fi

if test "$phase" = after; then
  : "${LMATELAB_PREVIEW_BEFORE_DIR:?after snapshot requires the before evidence directory}"
  before_dir=$(readlink -f "$LMATELAB_PREVIEW_BEFORE_DIR")
  case "$before_dir" in
    "$evidence_parent"/before-*) ;;
    *)
      printf 'before evidence directory escapes expected root: %s\n' "$before_dir" >&2
      exit 1
      ;;
  esac
  test -d "$before_dir"
  test ! -L "$before_dir"
  (cd "$before_dir" && sha256sum -c manifest.sha256 && sha256sum -c manifest.txt)
  for name in \
    current-target.txt \
    stable-eln.sha256 \
    stable-digests.sha256 \
    stable-eln-integrity.txt \
    stable-digests-integrity.txt \
    stable-service-job-id.txt \
    stable-service-node.txt \
    stable-service-port.txt \
    stable-service-commit.txt \
    stable-health-live.json; do
    cmp "$before_dir/$name" "$evidence/$name"
  done
  printf '%s\n' 'stable state matches before snapshot' > "$evidence/comparison.txt"
fi

cd "$evidence"
find . -maxdepth 1 -type f ! -name manifest.txt ! -name manifest.sha256 -print0 \
  | sort -z \
  | xargs -0 sha256sum > manifest.txt
sha256sum manifest.txt > manifest.sha256
sha256sum -c manifest.sha256
sha256sum -c manifest.txt
printf '%s\n' "$evidence"
