#!/bin/bash
set -euo pipefail
umask 077

project=/home/scc/pb23030683/projects/LMateLab-107Cup
root=/home/scc/pb23030683/lmatelab-107cup
commit="${1:?usage: submit-workflow-preview-service.sh MERGED_MAIN_COMMIT}"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]]

git -C "$project" fetch --quiet origin main
test "$(git -C "$project" rev-parse origin/main)" = "$commit"
test "$(git -C "$project" rev-parse 'origin/main^{commit}')" = "$commit"
test "$(git -C "$project" rev-parse HEAD)" = "$commit"
test -z "$(git -C "$project" status --porcelain --untracked-files=normal)"

release="$root/workflow-previews/$commit"
test -d "$release"
test "$(<"$release/commit.txt")" = "$commit"
test "$(<"$release/release-kind.txt")" = preview
test "$(<"$release/data-mode.txt")" = live
(cd "$release" && sha256sum -c manifest.sha256 >/dev/null && sha256sum -c manifest.txt >/dev/null)

mkdir -p "$root/logs" "$root/runtime/workflow-previews/$commit"
job_id=$(sbatch --parsable \
  --export=ALL,LMATELAB_WORKFLOW_PREVIEW_COMMIT="$commit" \
  "$project/deploy/107cup/workflow-preview-service.slurm")
job_id="${job_id%%;*}"
[[ "$job_id" =~ ^[0-9]+$ ]]
printf '%s\n' "$job_id" > "$root/runtime/workflow-previews/$commit/last-service-job-id"
printf '%s\n' "$job_id"
