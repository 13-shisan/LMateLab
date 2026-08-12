#!/bin/bash
set -euo pipefail
umask 077

project=/home/scc/pb23030683/projects/LMateLab-107Cup
root=/home/scc/pb23030683/lmatelab-107cup
commit="${1:?usage: submit-preview-build.sh MERGED_MAIN_COMMIT}"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]]

git -C "$project" fetch --quiet origin main
test "$(git -C "$project" rev-parse origin/main)" = "$commit"
test "$(git -C "$project" rev-parse 'origin/main^{commit}')" = "$commit"

mkdir -p "$root/logs" "$root/runtime/previews/$commit"
job_id=$(sbatch --parsable --export=ALL,LMATELAB_PREVIEW_COMMIT="$commit" \
  "$project/deploy/107cup/preview-build.slurm")
job_id="${job_id%%;*}"
[[ "$job_id" =~ ^[0-9]+$ ]]
printf '%s\n' "$job_id" > "$root/runtime/previews/$commit/build-job-id"
printf '%s\n' "$job_id"
