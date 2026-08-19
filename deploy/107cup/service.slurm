#!/bin/bash
#SBATCH --job-name=lmatelab-web
#SBATCH --account=competition
#SBATCH --partition=P107-RTX5090
#SBATCH --qos=qos_p107-rtx5090
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=4-00:00:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/service-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/service-%j.err

set -euo pipefail

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

printf '%s\n' "$SLURM_JOB_ID" > "$root/runtime/service-job-id"
printf '%s\n' "${SLURMD_NODENAME:-$(hostname)}" > "$root/runtime/service-node"
printf '%s\n' "$port" > "$root/runtime/service-port"
printf '%s\n' "$commit" > "$root/runtime/service-commit"
printf '%s\n' "$manifest_sha256" > "$root/runtime/service-manifest-sha256"
printf '%s\n' "$started_at" > "$root/runtime/service-started-at"

source "$python_env/bin/activate"
cd "$source_root/backend"
alembic -c alembic.ini upgrade head
alembic -c alembic_digest.ini upgrade head
python "$source_root/deploy/107cup/migrate-competition-roles.py" \
  --database "$root/data/db/eln.db" \
  --backup-dir "$root/backups/competition-roles" \
  --operator-alias "$LMATELAB_OPERATOR_ALIAS"

exec uvicorn main_107cup:app --host 0.0.0.0 --port "$port" --workers 1
