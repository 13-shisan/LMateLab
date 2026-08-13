#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

jq empty "$root/literature/schema.json"
jq empty "$root/literature/records.json"
jq empty "$root/literature/candidates.json"

jq -e '.records | all(.status == "full_incar" or .status == "verified_key_parameters")' "$root/literature/records.json" >/dev/null
jq -e '.generation_allowed == false and (.candidates | all(.status == "candidate_pending_fulltext" or .status == "rejected"))' "$root/literature/candidates.json" >/dev/null

duplicates=$(
  jq -r '.records[].record_id' "$root/literature/records.json"
  jq -r '.candidates[].record_id' "$root/literature/candidates.json"
)
if test -n "$(printf '%s\n' "$duplicates" | sort | uniq -d)"; then
  echo "ERROR: duplicate literature record_id" >&2
  printf '%s\n' "$duplicates" | sort | uniq -d >&2
  exit 1
fi

echo "Literature records and quarantine candidates passed validation."
