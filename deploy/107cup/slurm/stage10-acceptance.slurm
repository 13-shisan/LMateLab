#!/bin/bash
#SBATCH --job-name=lmatelab-stage10-acceptance
#SBATCH --account=competition
#SBATCH --partition=P107-A100
#SBATCH --qos=qos_p107-a100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=00:20:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/stage10-acceptance-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/stage10-acceptance-%j.err

set -euo pipefail
umask 077

: "${SLURM_JOB_ID:?stage10-acceptance.slurm must run through Slurm}"
: "${LMATELAB_STAGE10_EXPECTED_COMMIT:?fixed merged main commit is required}"
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
test "$commit" = "$LMATELAB_STAGE10_EXPECTED_COMMIT"
test -f "$release/source/deploy/107cup/slurm/stage10-acceptance.py"
output_dir="$root/evidence/stage10/acceptance-$SLURM_JOB_ID"
test ! -e "$output_dir"

export DATABASE_URL="sqlite:///$root/data/db/eln.db"
export DIGEST_DATABASE_URL="sqlite:///$root/data/db/digests.db"
export LMATELAB_WORKFLOW_ROOT="$root/data/workflows"
export LMATELAB_RELEASE_ROOT="$release"
export LMATELAB_FRONTEND_DIST="$release/frontend-dist"
export LMATELAB_GIT_COMMIT="$commit"
export LMATELAB_COORDINATOR_ENABLED=0
export MPLCONFIGDIR="$root/runtime/cache/matplotlib"
export PYTHONPATH="$release/source/backend"

mkdir -p "$MPLCONFIGDIR" "$root/evidence/stage10"
cd "$release/source/backend"
exec "$python_env/bin/python" \
  "$release/source/deploy/107cup/slurm/stage10-acceptance.py" \
  --root "$root" \
  --output-dir "$output_dir"
