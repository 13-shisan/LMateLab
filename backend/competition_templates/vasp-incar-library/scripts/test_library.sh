#!/bin/sh
set -eu

root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

jq empty "$root/index.json"
jq empty "$root/request.example.json"

jq -r '.templates[].file, .materials[].path' "$root/index.json" |
while IFS= read -r relative; do
  test -f "$root/$relative" || {
    echo "ERROR: index target missing: $relative" >&2
    exit 1
  }
done

find "$root/materials" -type f -name 'INCAR.*.example' -print0 |
while IFS= read -r -d '' input; do
  "$root/scripts/check_incar.sh" "$input"
done

echo "Library index and concrete INCAR examples passed static checks."
"$root/scripts/validate_literature.sh"
