#!/bin/bash
set -euo pipefail
umask 077

root=/home/scc/pb23030683/lmatelab-107cup
project=/home/scc/pb23030683/projects/LMateLab-107Cup

test -d "$project/.git"
test -z "$(git -C "$project" status --porcelain)"
git -C "$project" fetch --quiet origin main
head_commit=$(git -C "$project" rev-parse HEAD)
main_commit=$(git -C "$project" rev-parse origin/main)
test "$head_commit" = "$main_commit"
[[ "$head_commit" =~ ^[0-9a-f]{40}$ ]]

test -L "$root/current"
release=$(readlink -f "$root/current")
test "$release" = "$root/releases/$head_commit"
test -f "$release/commit.txt"
test "$(<"$release/commit.txt")" = "$head_commit"
acceptance="$release/source/deploy/107cup/slurm/stage10-acceptance.slurm"
test -f "$acceptance"
mkdir -p "$root/logs" "$root/runtime" "$root/evidence/stage10"

job_id=$(sbatch --parsable \
  --export="ALL,LMATELAB_STAGE10_EXPECTED_COMMIT=$head_commit" \
  "$acceptance")
printf '%s\n' "$job_id" > "$root/runtime/stage10-acceptance-job-id"
printf '%s\n' "$job_id"
