#!/bin/bash
#SBATCH --job-name=lmatelab-stage6-probe
#SBATCH --account=competition
#SBATCH --partition=P107-RTX5090
#SBATCH --qos=qos_p107-rtx5090
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=256M
#SBATCH --time=00:03:00

set -euo pipefail
umask 077

: "${SLURM_JOB_ID:?probe.slurm must run through Slurm}"

if test "$#" -ne 3; then
  printf 'usage: probe.slurm success|fail|cancel WORKFLOW_UUID ATTEMPT_UUID\n' >&2
  exit 64
fi

mode=$1
workflow_id=$2
attempt_id=$3
uuid_pattern='^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$'

case "$mode" in
  success|fail|cancel) ;;
  *)
    printf 'invalid probe mode\n' >&2
    exit 64
    ;;
esac

if ! [[ "$workflow_id" =~ $uuid_pattern ]] || ! [[ "$attempt_id" =~ $uuid_pattern ]]; then
  printf 'invalid probe identity\n' >&2
  exit 64
fi

printf 'stage6-probe job=%s mode=%s workflow=%s attempt=%s\n' \
  "$SLURM_JOB_ID" "$mode" "$workflow_id" "$attempt_id"

case "$mode" in
  success)
    printf 'stage6-probe completed\n'
    ;;
  fail)
    printf 'stage6-probe deliberate failure\n' >&2
    exit 42
    ;;
  cancel)
    while true; do
      sleep 1
    done
    ;;
esac
