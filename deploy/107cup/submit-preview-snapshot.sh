#!/bin/bash
set -euo pipefail

project=/home/scc/pb23030683/projects/LMateLab-107Cup
root=/home/scc/pb23030683/lmatelab-107cup
phase="${1:?usage: submit-preview-snapshot.sh before|after COMMIT [BEFORE_DIR]}"
commit="${2:?usage: submit-preview-snapshot.sh before|after COMMIT [BEFORE_DIR]}"
before_dir="${3:-}"

[[ "$phase" =~ ^(before|after)$ ]]
[[ "$commit" =~ ^[0-9a-f]{40}$ ]]
if test "$phase" = before; then
  test -z "$before_dir"
else
  test -n "$before_dir"
fi

mkdir -p "$root/logs"
job_id=$(sbatch --parsable \
  --export=ALL,LMATELAB_PREVIEW_COMMIT="$commit",LMATELAB_PREVIEW_SNAPSHOT_PHASE="$phase",LMATELAB_PREVIEW_BEFORE_DIR="$before_dir" \
  "$project/deploy/107cup/preview-snapshot.slurm")
job_id="${job_id%%;*}"
[[ "$job_id" =~ ^[0-9]+$ ]]
printf '%s\n' "$job_id"
