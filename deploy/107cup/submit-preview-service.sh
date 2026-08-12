#!/bin/bash
set -euo pipefail
umask 077

project=/home/scc/pb23030683/projects/LMateLab-107Cup
root=/home/scc/pb23030683/lmatelab-107cup
commit="${1:?usage: submit-preview-service.sh MERGED_MAIN_COMMIT}"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]]

release="$root/previews/$commit"
test -d "$release"
test "$(<"$release/commit.txt")" = "$commit"
test "$(<"$release/release-kind.txt")" = preview
test "$(<"$release/data-mode.txt")" = demo
(cd "$release" && sha256sum -c manifest.sha256 && sha256sum -c manifest.txt)

mkdir -p "$root/logs" "$root/runtime/previews/$commit"
job_id=$(sbatch --parsable --export=ALL,LMATELAB_PREVIEW_COMMIT="$commit" \
  "$project/deploy/107cup/preview-service.slurm")
job_id="${job_id%%;*}"
[[ "$job_id" =~ ^[0-9]+$ ]]
printf '%s\n' "$job_id" > "$root/runtime/previews/$commit/last-service-job-id"
printf '%s\n' "$job_id"
