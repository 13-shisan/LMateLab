#!/bin/bash
set -euo pipefail
umask 077

project=/home/scc/pb23030683/projects/LMateLab-107Cup
root=/home/scc/pb23030683/lmatelab-107cup
commit="${1:?usage: submit-workflow-preview-build.sh MERGED_MAIN_COMMIT}"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]]

git -C "$project" fetch --quiet origin main
test "$(git -C "$project" rev-parse origin/main)" = "$commit"
test "$(git -C "$project" rev-parse 'origin/main^{commit}')" = "$commit"
test "$(git -C "$project" rev-parse HEAD)" = "$commit"
test -z "$(git -C "$project" status --porcelain --untracked-files=normal)"

mkdir -p "$root/logs" "$root/runtime/workflow-previews/$commit"
job_id=$(sbatch --parsable \
  --export=ALL,LMATELAB_WORKFLOW_PREVIEW_COMMIT="$commit" \
  "$project/deploy/107cup/workflow-preview-build.slurm")
job_id="${job_id%%;*}"
[[ "$job_id" =~ ^[0-9]+$ ]]
printf '%s\n' "$job_id" > "$root/runtime/workflow-previews/$commit/build-job-id"
printf '%s\n' "$job_id"
