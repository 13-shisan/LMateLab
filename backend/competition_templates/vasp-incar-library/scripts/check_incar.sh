#!/bin/sh
set -eu

file=${1:-INCAR}
test -f "$file" || { echo "ERROR: file not found: $file" >&2; exit 2; }

status=0
active=$(sed 's/[#!].*$//' "$file")
if echo "$active" | grep -n '{{[^}]*}}'; then
  echo "ERROR: unresolved template placeholders" >&2
  status=1
fi

duplicates=$(sed 's/[#!].*$//' "$file" | sed -n 's/^[[:space:]]*\([A-Za-z0-9_\/]*\)[[:space:]]*=.*/\1/p' | tr '[:lower:]' '[:upper:]' | sort | uniq -d)
if test -n "$duplicates"; then
  echo "ERROR: duplicate active tags:" >&2
  echo "$duplicates" >&2
  status=1
fi

if grep -Eiq '^[[:space:]]*ICHARG[[:space:]]*=[[:space:]]*11([[:space:]#!]|$)' "$file"; then
  echo "CHECK: ICHARG=11 requires a compatible converged CHGCAR"
fi
if grep -Eiq '^[[:space:]]*ISTART[[:space:]]*=[[:space:]]*1([[:space:]#!]|$)' "$file"; then
  echo "CHECK: ISTART=1 requires a compatible WAVECAR"
fi
if grep -Eiq '^[[:space:]]*LDAU[[:space:]]*=[[:space:]]*(\.TRUE\.|T)' "$file"; then
  echo "CHECK: cite U/J convention and verify species-order arrays"
fi
if grep -Eiq '^[[:space:]]*ISIF[[:space:]]*=[[:space:]]*3([[:space:]#!]|$)' "$file"; then
  echo "CHECK: confirm ISIF=3 is intentional for a fully periodic 3D cell"
fi

exit "$status"
