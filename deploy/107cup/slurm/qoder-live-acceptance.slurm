#!/usr/bin/env bash
#SBATCH --job-name=lmatelab-qoder-acceptance
#SBATCH --account=competition
#SBATCH --partition=P107-RTX5090
#SBATCH --qos=qos_p107-rtx5090
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:10:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/qoder-acceptance-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/qoder-acceptance-%j.err

set -euo pipefail
umask 077

: "${SLURM_JOB_ID:?qoder-live-acceptance.slurm must run through Slurm}"

root=/home/scc/pb23030683/lmatelab-107cup
runtime_env="$root/config/runtime.env"
release=$(readlink -f "$root/current")
source_root="$release/source"
python_env="$root/envs/python"

test -f "$runtime_env"
test -f "$source_root/deploy/107cup/slurm/qoder-live-acceptance.py"
test -x "$python_env/bin/python"

set -a
source "$runtime_env"
set +a

export LMATELAB_QODER_REAL_NETWORK_AUTHORIZED=1
export LMATELAB_STRUCTURE_LIBRARY_DB="${LMATELAB_STRUCTURE_LIBRARY_DB:-$root/data/qmof/current/structures.sqlite}"
export LMATELAB_QMOF_CIF_ROOT="${LMATELAB_QMOF_CIF_ROOT:-$root/data/qmof/current/relaxed_structures}"
export LMATELAB_PRIMARY_DATABASE="$root/data/db/eln.db"
export PYTHONPATH="$source_root/backend"

test -f "$LMATELAB_STRUCTURE_LIBRARY_DB"
test -d "$LMATELAB_QMOF_CIF_ROOT"
test -f "$LMATELAB_PRIMARY_DATABASE"

source "$python_env/bin/activate"
cd "$source_root/backend"
exec python "$source_root/deploy/107cup/slurm/qoder-live-acceptance.py"
