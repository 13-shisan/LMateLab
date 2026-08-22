#!/usr/bin/env bash
#SBATCH --job-name=lmatelab-agent-worker
#SBATCH --account=competition
#SBATCH --partition=P107-A100
#SBATCH --qos=qos_p107-a100
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/agent-worker-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/agent-worker-%j.err

set -euo pipefail

: "${SLURM_JOB_ID:?agent-worker.slurm must run through Slurm}"
: "${LMATELAB_COMPETITION_AGENT_ENABLED:=0}"

if [[ "$LMATELAB_COMPETITION_AGENT_ENABLED" != "1" ]]; then
  printf 'competition Agent is disabled\n' >&2
  exit 2
fi

root=/home/scc/pb23030683/lmatelab-107cup
release=$(readlink -f "$root/current")
test -x "$release/python/bin/python"

export PYTHONPATH="$release/source/backend"
exec "$release/python/bin/python" -m services.competition_agent.worker \
  --poll-seconds 1 --max-idle-cycles 240
