#!/bin/bash
#SBATCH --job-name=lmatelab-stage7-acceptance
#SBATCH --account=competition
#SBATCH --partition=P107-RTX5090
#SBATCH --qos=qos_p107-rtx5090
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/stage7-acceptance-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/stage7-acceptance-%j.err

set -euo pipefail
umask 077

: "${SLURM_JOB_ID:?stage7-acceptance.slurm must run through Slurm}"
root=/home/scc/pb23030683/lmatelab-107cup
runtime_env="$root/config/runtime.env"
python_env="$root/envs/python"

test -f "$runtime_env"
test -x "$python_env/bin/python"
test -L "$root/current"
set -a
source "$runtime_env"
set +a

release=$(readlink -f "$root/current")
commit=$(<"$release/commit.txt")
test -f "$release/source/deploy/107cup/slurm/stage7-acceptance.py"
test -f "$release/frontend-dist/index.html"

export LMATELAB_WORKFLOW_ROOT="$root/data/workflows"
export LMATELAB_RELEASE_ROOT="$release"
export LMATELAB_SLURM_PROBE_SCRIPT="$release/source/deploy/107cup/slurm/probe.slurm"
export LMATELAB_VASP_STAGE_SCRIPT="$release/source/deploy/107cup/slurm/vasp-stage.slurm"
export LMATELAB_FRONTEND_DIST="$release/frontend-dist"
export LMATELAB_GIT_COMMIT="$commit"
export LMATELAB_COORDINATOR_ENABLED=0
export PYTHONPATH="$release/source/backend"

cd "$release/source/backend"
exec "$python_env/bin/python" \
  "$release/source/deploy/107cup/slurm/stage7-acceptance.py" \
  --profile scf_nonconvergence_v1
