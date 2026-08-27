#!/bin/bash
set -euo pipefail
umask 077

project=/home/scc/pb23030683/projects/LMateLab-107Cup
root=/home/scc/pb23030683/lmatelab-107cup
test "$PWD" = "$project"
test -z "$(git status --porcelain)"
mkdir -p -m 700 "$root/logs" "$root/evidence/stage7"

job_id=$(sbatch --parsable "$project/deploy/107cup/slurm/generic-vaspkit-preflight.slurm")
[[ "$job_id" =~ ^[1-9][0-9]*$ ]]
printf 'GENERIC_VASPKIT_PREFLIGHT_JOB=%s\n' "$job_id"
