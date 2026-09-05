#!/usr/bin/env bash
#SBATCH --job-name=lmatelab-agent-worker
#SBATCH --account=competition
#SBATCH --partition=P107-A100
#SBATCH --qos=qos_p107-a100
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=4-00:00:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/agent-worker-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/agent-worker-%j.err

set -euo pipefail
umask 077

: "${SLURM_JOB_ID:?agent-worker.slurm must run through Slurm}"

root=/home/scc/pb23030683/lmatelab-107cup
runtime_env="$root/config/runtime.env"
python_env="$root/envs/python"

test -f "$runtime_env"
test -L "$root/current"
test -x "$python_env/bin/python"

set -a
source "$runtime_env"
set +a
: "${LMATELAB_COMPETITION_AGENT_ENABLED:=0}"

if [[ "$LMATELAB_COMPETITION_AGENT_ENABLED" != "1" ]]; then
  printf 'competition Agent is disabled\n' >&2
  exit 2
fi

release=$(readlink -f "$root/current")
source_root="$release/source"
commit=$(<"$release/commit.txt")
manifest_sha256=$(cut -d ' ' -f 1 "$release/manifest.sha256")
started_at=$(date --iso-8601=seconds)

test -f "$source_root/backend/main_107cup.py"
test -f "$source_root/deploy/107cup/agent_worker_control.py"

export PYTHONPATH="$source_root/backend"
source "$python_env/bin/activate"
cd "$source_root/backend"
python -c "import models_competition_agent; from database import SessionLocal; SessionLocal().close()"

worker_pid=
shutdown_worker() {
  trap - TERM INT
  if test -n "${worker_pid:-}" && kill -0 "$worker_pid" 2>/dev/null; then
    kill -TERM "$worker_pid"
  fi
  if test -n "${worker_pid:-}"; then
    set +e
    wait "$worker_pid"
    worker_status=$?
    set -e
  else
    worker_status=0
  fi
  python "$source_root/deploy/107cup/agent_worker_control.py" publish \
    --job-id "$SLURM_JOB_ID" --node "${SLURMD_NODENAME:-$(hostname)}" \
    --commit "$commit" --manifest-sha256 "$manifest_sha256" \
    --started-at "$started_at" --status stopped --exit-code "$worker_status" || true
  exit 0
}
trap shutdown_worker TERM INT

python -m services.competition_agent.worker \
  --poll-seconds 1 --max-idle-cycles 0 &
worker_pid=$!
sleep 1
kill -0 "$worker_pid"
python "$source_root/deploy/107cup/agent_worker_control.py" publish \
  --job-id "$SLURM_JOB_ID" --node "${SLURMD_NODENAME:-$(hostname)}" \
  --commit "$commit" --manifest-sha256 "$manifest_sha256" \
  --started-at "$started_at" --status running

set +e
wait "$worker_pid"
worker_status=$?
set -e
python "$source_root/deploy/107cup/agent_worker_control.py" publish \
  --job-id "$SLURM_JOB_ID" --node "${SLURMD_NODENAME:-$(hostname)}" \
  --commit "$commit" --manifest-sha256 "$manifest_sha256" \
  --started-at "$started_at" --status stopped --exit-code "$worker_status" || true
exit "$worker_status"
