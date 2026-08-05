#!/usr/bin/env bash
set -euo pipefail

INGEST_SCRIPT="${VASP_INGEST_SCRIPT:-/storage/Pwjb/ase-db/ase-data+storage.sh}"
JOB_NAME="${VASP_INGEST_JOB_NAME:-vasp-db-refresh}"
STATE_DIR="${VASP_REFRESH_STATE_DIR:-${HOME}/.local/state/lmatelab}"
STATE_FILE="${STATE_DIR}/vasp-db-refresh.last-submit"

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

command -v qsub >/dev/null 2>&1 || die "qsub is unavailable; run this wrapper on a PBS login/submit node"
[[ -f "${INGEST_SCRIPT}" ]] || die "ingestion script not found: ${INGEST_SCRIPT}"
[[ -r "${INGEST_SCRIPT}" ]] || die "ingestion script is not readable: ${INGEST_SCRIPT}"

if command -v qstat >/dev/null 2>&1; then
  current_user="${USER:-$(id -un)}"
  if qstat -u "${current_user}" 2>/dev/null | awk -v name="${JOB_NAME}" 'NR > 2 && $4 == name { found=1 } END { exit !found }'; then
    die "a PBS job named ${JOB_NAME} is already queued or running"
  fi
fi

mkdir -p "${STATE_DIR}"
cd "$(dirname "${INGEST_SCRIPT}")"
job_id="$(qsub -N "${JOB_NAME}" "${INGEST_SCRIPT}")"
[[ -n "${job_id}" ]] || die "qsub returned an empty job id"

printf '%s\t%s\t%s\t%s\n' \
  "$(date --iso-8601=seconds)" "${job_id}" "$(hostname -f 2>/dev/null || hostname)" "${INGEST_SCRIPT}" \
  > "${STATE_FILE}"

printf 'Submitted %s as %s\n' "${INGEST_SCRIPT}" "${job_id}"
printf 'Submission record: %s\n' "${STATE_FILE}"
