#!/usr/bin/env bash
set -euo pipefail
umask 077

root=/home/scc/pb23030683/lmatelab-107cup
project=/home/scc/pb23030683/projects/LMateLab-107Cup

test "$(id -un)" = pb23030683
test -d "$project/.git"
test -z "$(git -C "$project" status --porcelain)"
test -f "$project/deploy/107cup/qmof-library.slurm"
test -L "$root/current"
commit=$(git -C "$project" rev-parse HEAD)
test "$commit" = "$(git -C "$project" rev-parse origin/main)"
test "$commit" = "$(<"$root/current/commit.txt")"
mkdir -p "$root/logs" "$root/runtime"

job_id=$(sbatch --parsable \
  --export="ALL,LMATELAB_QMOF_SOURCE_COMMIT=$commit" \
  "$project/deploy/107cup/qmof-library.slurm")
[[ "$job_id" =~ ^[0-9]+$ ]]
printf '%s\n' "$job_id" > "$root/runtime/qmof-library-job-id"
printf '%s\n' "$job_id"
