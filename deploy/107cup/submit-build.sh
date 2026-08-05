#!/bin/bash
set -euo pipefail

root=/home/scc/pb23030683/lmatelab-107cup
project=/home/scc/pb23030683/projects/LMateLab-107Cup

test -d "$project/.git"
test -f "$project/deploy/107cup/build.slurm"
mkdir -p "$root/logs" "$root/runtime"

job_id=$(sbatch --parsable "$project/deploy/107cup/build.slurm")
printf '%s\n' "$job_id" > "$root/runtime/build-job-id"
printf '%s\n' "$job_id"
