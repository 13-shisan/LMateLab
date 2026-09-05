#!/bin/bash
#SBATCH --job-name=lmatelab-web
#SBATCH --account=competition
#SBATCH --partition=P107-A100
#SBATCH --qos=qos_p107-a100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=4-00:00:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/service-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/service-%j.err

set -euo pipefail
umask 077

: "${SLURM_JOB_ID:?service.slurm must run through Slurm}"

root=/home/scc/pb23030683/lmatelab-107cup
runtime_env="$root/config/runtime.env"
python_env="$root/envs/python"

test -f "$runtime_env"
test -L "$root/current"
test -x "$python_env/bin/python"

set -a
source "$runtime_env"
set +a
: "${JWT_SECRET:?JWT_SECRET must be configured}"
: "${LMATELAB_OPERATOR_ALIAS:?LMATELAB_OPERATOR_ALIAS must be configured}"

release=$(readlink -f "$root/current")
source_root="$release/source"
frontend_root="$release/frontend-dist"
commit=$(<"$release/commit.txt")
manifest_sha256=$(cut -d ' ' -f 1 "$release/manifest.sha256")
started_at=$(date --iso-8601=seconds)
port="${LMATELAB_PORT:-18731}"

test -f "$frontend_root/index.html"
test -f "$source_root/backend/main_107cup.py"
test -f "$source_root/deploy/107cup/service_recovery.py"

export LMATELAB_RELEASE_ROOT="$release"
export LMATELAB_WORKFLOW_ROOT="$root/data/workflows"
export LMATELAB_SLURM_PROBE_SCRIPT="$release/source/deploy/107cup/slurm/probe.slurm"
export LMATELAB_VASP_STAGE_SCRIPT="$release/source/deploy/107cup/slurm/vasp-stage.slurm"
export LMATELAB_COORDINATOR_ENABLED="${LMATELAB_COORDINATOR_ENABLED:-1}"
export LMATELAB_COORDINATOR_INTERVAL_SECONDS="${LMATELAB_COORDINATOR_INTERVAL_SECONDS:-10}"
export LMATELAB_COORDINATOR_BATCH_LIMIT="${LMATELAB_COORDINATOR_BATCH_LIMIT:-8}"
export LMATELAB_FRONTEND_DIST="$frontend_root"
export LMATELAB_GIT_COMMIT="$commit"
export LMATELAB_MANIFEST_SHA256="$manifest_sha256"
export LMATELAB_STARTED_AT="$started_at"
export MPLCONFIGDIR="$root/runtime/cache/matplotlib"
mkdir -p "$MPLCONFIGDIR" "$VASP_ELEMENTS_CACHE_DIR"

source "$python_env/bin/activate"
cd "$source_root/backend"
database_label="${SLURM_JOB_ID}.${SLURM_RESTART_COUNT:-0}"
python "$source_root/deploy/107cup/prepare-databases.py" backup \
  --database "$root/data/db/eln.db" \
  --database "$root/data/db/digests.db" \
  --backup-dir "$root/backups/pre-migration" \
  --label "$database_label"
alembic -c alembic.ini upgrade head
alembic -c alembic_digest.ini upgrade head
alembic -c alembic.ini current --check-heads
alembic -c alembic_digest.ini current --check-heads
python "$source_root/deploy/107cup/prepare-databases.py" verify \
  --database "$root/data/db/eln.db" \
  --database "$root/data/db/digests.db"
python "$source_root/deploy/107cup/migrate-competition-roles.py" \
  --database "$root/data/db/eln.db" \
  --backup-dir "$root/backups/competition-roles" \
  --operator-alias "$LMATELAB_OPERATOR_ALIAS"

server_pid=
shutdown_server() {
  trap - TERM INT
  if test -n "${server_pid:-}" && kill -0 "$server_pid" 2>/dev/null; then
    kill -TERM "$server_pid"
  fi
  if test -n "${server_pid:-}"; then
    set +e
    wait "$server_pid"
    set -e
  fi
  exit 0
}
trap shutdown_server TERM INT

uvicorn main_107cup:app --host 0.0.0.0 --port "$port" --workers 1 &
server_pid=$!

ready=0
for _attempt in $(seq 1 60); do
  if ! kill -0 "$server_pid" 2>/dev/null; then
    break
  fi
  if curl --fail --silent --show-error --connect-timeout 2 --max-time 5 \
      "http://127.0.0.1:$port/api/health/live" >/dev/null \
    && curl --fail --silent --show-error --connect-timeout 2 --max-time 5 \
      "http://127.0.0.1:$port/api/health/ready" >/dev/null \
    && python "$source_root/deploy/107cup/service_recovery.py" verify-health \
      --job-id "$SLURM_JOB_ID" \
      --node "${SLURMD_NODENAME:-$(hostname)}" \
      --port "$port" \
      --commit "$commit" \
      --manifest-sha256 "$manifest_sha256" \
      --started-at "$started_at" >/dev/null; then
    ready=1
    break
  fi
  sleep 1
done

if test "$ready" -ne 1; then
  if kill -0 "$server_pid" 2>/dev/null; then
    kill -TERM "$server_pid"
  fi
  set +e
  wait "$server_pid"
  server_status=$?
  set -e
  printf 'service failed readiness before state publication; server_status=%s\n' \
    "$server_status" >&2
  exit 1
fi

python "$source_root/deploy/107cup/service_recovery.py" publish \
  --job-id "$SLURM_JOB_ID" \
  --node "${SLURMD_NODENAME:-$(hostname)}" \
  --port "$port" \
  --commit "$commit" \
  --manifest-sha256 "$manifest_sha256" \
  --started-at "$started_at"

set +e
wait "$server_pid"
server_status=$?
set -e
exit "$server_status"
