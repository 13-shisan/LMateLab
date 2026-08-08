#!/bin/bash
#SBATCH --job-name=lmatelab-rollback-smoke
#SBATCH --account=competition
#SBATCH --partition=P107-A100
#SBATCH --qos=qos_p107-a100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:10:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/rollback-smoke-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/rollback-smoke-%j.err

set -euo pipefail
umask 077

: "${SLURM_JOB_ID:?rollback-smoke.slurm must run through Slurm}"
: "${LMATELAB_ROLLBACK_RELEASE:?set the 40-character release commit}"
[[ "$LMATELAB_ROLLBACK_RELEASE" =~ ^[0-9a-f]{40}$ ]]

root=/home/scc/pb23030683/lmatelab-107cup
python_env="$root/envs/python"
release="$root/releases/$LMATELAB_ROLLBACK_RELEASE"
smoke_root="$root/rollback-smoke/$SLURM_JOB_ID"
evidence_root="$root/evidence/rollback/$SLURM_JOB_ID"
port="${LMATELAB_ROLLBACK_PORT:-18732}"
server_pid=

cleanup() {
  status=$?
  if test -n "${server_pid:-}" && kill -0 "$server_pid" 2>/dev/null; then
    kill -TERM "$server_pid"
    wait "$server_pid" || true
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

test -d "$release"
test "$(dirname "$(readlink -f "$release")")" = "$root/releases"
test -f "$release/commit.txt"
test "$(<"$release/commit.txt")" = "$LMATELAB_ROLLBACK_RELEASE"
test -x "$python_env/bin/python"
test ! -e "$smoke_root"
test ! -e "$evidence_root"

mkdir -p \
  "$smoke_root/data/db" \
  "$smoke_root/data/uploads" \
  "$smoke_root/data/custom/vasp" \
  "$smoke_root/data/custom/qe_epw" \
  "$smoke_root/data/issues" \
  "$smoke_root/runtime/cache/vasp-elements" \
  "$smoke_root/runtime/cache/matplotlib" \
  "$smoke_root/backups/competition-roles" \
  "$evidence_root"

production_current_before=$(readlink -f "$root"/current)
ln -s "$production_current_before" "$smoke_root/rollback-current"
printf '%s\n' "$production_current_before" > "$evidence_root/production-current-before.txt"
printf '%s\n' "$(readlink -f "$smoke_root/rollback-current")" \
  > "$evidence_root/rollback-current-before.txt"

ln -s "$release" "$smoke_root/rollback-current.next"
mv -Tf "$smoke_root/rollback-current.next" "$smoke_root/rollback-current"
printf '%s\n' "$(readlink -f "$smoke_root/rollback-current")" \
  > "$evidence_root/rollback-current-after.txt"
test "$(readlink -f "$smoke_root/rollback-current")" = "$release"

(
  cd "$release"
  sha256sum -c manifest.sha256
  sha256sum -c manifest.txt
) > "$evidence_root/release-manifest-check-before.txt"

set -a
source "$root/config/runtime.env"
set +a
: "${JWT_SECRET:?JWT_SECRET must be configured}"
: "${LMATELAB_OPERATOR_ALIAS:?LMATELAB_OPERATOR_ALIAS must be configured}"

source_root="$release/source"
frontend_root="$release/frontend-dist"
manifest_sha256=$(cut -d ' ' -f 1 "$release/manifest.sha256")
started_at=$(date --iso-8601=seconds)

export LMATELAB_DATA_DIR="$smoke_root/data"
export LMATELAB_FRONTEND_DIST="$frontend_root"
export LMATELAB_GIT_COMMIT="$LMATELAB_ROLLBACK_RELEASE"
export LMATELAB_MANIFEST_SHA256="$manifest_sha256"
export LMATELAB_STARTED_AT="$started_at"
export LMATELAB_PORT="$port"
export DATABASE_URL="sqlite:///$smoke_root/data/db/eln.db"
export DIGEST_DATABASE_URL="sqlite:///$smoke_root/data/db/digests.db"
export UPLOADS_ROOT="$smoke_root/data/uploads"
export VASP_UPLOADS_ROOT="$smoke_root/data/uploads"
export VASP_CUSTOM_DB_ROOT="$smoke_root/data/custom/vasp"
export QE_EPW_CUSTOM_DB_ROOT="$smoke_root/data/custom/qe_epw"
export VASP_ELEMENTS_CACHE_DIR="$smoke_root/runtime/cache/vasp-elements"
export ISSUES_DIR="$smoke_root/data/issues"
export CHANGELOG_PATH="$smoke_root/data/changelog.md"
export MPLCONFIGDIR="$smoke_root/runtime/cache/matplotlib"

test -f "$frontend_root/index.html"
test -f "$source_root/backend/main_107cup.py"

source "$python_env/bin/activate"
cd "$source_root/backend"
alembic -c alembic.ini upgrade head \
  > "$evidence_root/alembic-primary.txt" 2>&1
alembic -c alembic_digest.ini upgrade head \
  > "$evidence_root/alembic-digest.txt" 2>&1
python - "$smoke_root/data/db/eln.db" "$LMATELAB_OPERATOR_ALIAS" \
  > "$evidence_root/synthetic-operator.txt" <<'PY'
import sqlite3
import sys

with sqlite3.connect(sys.argv[1]) as connection:
    connection.execute(
        "INSERT INTO users (email, password_hash, name, alias, role) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            "rollback-smoke@example.invalid",
            "rollback-smoke-placeholder",
            "Rollback Smoke Operator",
            sys.argv[2],
            "root",
        ),
    )
    connection.commit()
print("created isolated synthetic root operator")
PY
python "$source_root/deploy/107cup/migrate-competition-roles.py" \
  --database "$smoke_root/data/db/eln.db" \
  --backup-dir "$smoke_root/backups/competition-roles" \
  --operator-alias "$LMATELAB_OPERATOR_ALIAS" \
  > "$evidence_root/role-migration.txt" 2>&1

uvicorn main_107cup:app --host 127.0.0.1 --port "$port" --workers 1 \
  > "$evidence_root/uvicorn.out" 2> "$evidence_root/uvicorn.err" &
server_pid=$!

ready=0
for _attempt in $(seq 1 60); do
  if curl --fail --silent --show-error \
      "http://127.0.0.1:$port/api/health/live" \
      > "$evidence_root/live.json.tmp" 2>/dev/null \
    && curl --fail --silent --show-error \
      "http://127.0.0.1:$port/api/health/ready" \
      > "$evidence_root/ready.json.tmp" 2>/dev/null; then
    mv "$evidence_root/live.json.tmp" "$evidence_root/live.json"
    mv "$evidence_root/ready.json.tmp" "$evidence_root/ready.json"
    ready=1
    break
  fi
  kill -0 "$server_pid"
  sleep 1
done
test "$ready" -eq 1

python - "$evidence_root/live.json" "$LMATELAB_ROLLBACK_RELEASE" \
  "$SLURM_JOB_ID" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    response = json.load(handle)
assert response["status"] == "ok", response
assert response["commit"] == sys.argv[2], response
assert response["job_id"] == sys.argv[3], response
PY

python - "$smoke_root/data/db/eln.db" "$smoke_root/data/db/digests.db" \
  > "$evidence_root/sqlite-integrity.txt" <<'PY'
import sqlite3
import sys

for database_path in sys.argv[1:]:
    with sqlite3.connect(database_path) as connection:
        result = connection.execute("PRAGMA integrity_check;").fetchone()[0]
    print(f"{database_path}: {result}")
    assert result == "ok", (database_path, result)
PY

kill -TERM "$server_pid"
wait "$server_pid"
server_pid=

production_current_after=$(readlink -f "$root"/current)
printf '%s\n' "$production_current_after" > "$evidence_root/production-current-after.txt"
test "$production_current_before" = "$production_current_after"

(
  cd "$release"
  sha256sum -c manifest.sha256
  sha256sum -c manifest.txt
) > "$evidence_root/release-manifest-check-after.txt"

printf '%s\n' \
  "job_id=$SLURM_JOB_ID" \
  "node=${SLURMD_NODENAME:-$(hostname)}" \
  "rollback_release=$LMATELAB_ROLLBACK_RELEASE" \
  "rollback_port=$port" \
  "smoke_root=$smoke_root" \
  "evidence_root=$evidence_root" \
  "production_current=$production_current_after" \
  "completed_at=$(date --iso-8601=seconds)" \
  > "$evidence_root/SUCCESS.txt"

find "$evidence_root" -type f -print0 | sort -z | xargs -0 sha256sum \
  > "$smoke_root/evidence-manifest.sha256"
trap - EXIT INT TERM
