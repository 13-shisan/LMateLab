#!/bin/bash
set -euo pipefail

root=/home/scc/pb23030683/lmatelab-107cup
project=/home/scc/pb23030683/projects/LMateLab-107Cup

test -L "$root/current"
test -f "$root/config/runtime.env"
test -f "$project/deploy/107cup/service.slurm"
mkdir -p "$root/logs" "$root/runtime"

job_id=$(sbatch --parsable "$project/deploy/107cup/service.slurm")
printf '%s\n' "$job_id" > "$root/runtime/service-job-id"
printf '%s\n' "$job_id"
