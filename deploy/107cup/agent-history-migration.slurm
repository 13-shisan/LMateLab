#!/bin/bash
#SBATCH --job-name=lmatelab-agent-history
#SBATCH --account=competition
#SBATCH --partition=P107-A100
#SBATCH --qos=qos_p107-a100
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:10:00
#SBATCH --output=/home/scc/pb23030683/lmatelab-107cup/logs/agent-history-%j.out
#SBATCH --error=/home/scc/pb23030683/lmatelab-107cup/logs/agent-history-%j.err

set -euo pipefail
umask 077

: "${SLURM_JOB_ID:?agent-history-migration.slurm must run through Slurm}"

root=/home/scc/pb23030683/lmatelab-107cup
source_export="$root/migrations/agent-history/import.json"
archive_export="$root/migrations/agent-history/imported-$SLURM_JOB_ID.json"
report="$root/migrations/agent-history/report-$SLURM_JOB_ID.json"
target_database="$root/data/db/eln.db"
backup_dir="$root/backups/agent-history"
python_env="$root/envs/python"
release=$(readlink -f "$root/current")

test -x "$python_env/bin/python"
test -f "$source_export"
test ! -e "$archive_export"
test ! -e "$report"

"$python_env/bin/python" \
  "$release/source/deploy/107cup/migrate-agent-history.py" \
  --source-export "$source_export" \
  --target-database "$target_database" \
  --owner-email jbwu@mail.ustc.edu.cn \
  --backup-dir "$backup_dir" \
  --label "$SLURM_JOB_ID" \
  --report "$report" \
  --apply

mv "$source_export" "$archive_export"
chmod 600 "$archive_export" "$report"
