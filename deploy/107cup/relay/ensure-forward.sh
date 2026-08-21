#!/bin/bash
set -euo pipefail
umask 077

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
test -f "$script_dir/ensure_forward.py"

log=/home/Pwjb/.config/lmatelab-107cup-proxy/log/recovery.log
if test -e "$log" || test -L "$log"; then
  test -f "$log"
  test ! -L "$log"
  if test "$(stat -c '%s' "$log")" -gt 1048576; then
    rotated=$(mktemp "${log}.rotate.XXXXXX")
    trap 'rm -f -- "${rotated:-}"' EXIT INT TERM
    tail -c 262144 "$log" > "$rotated"
    chmod 600 "$rotated"
    mv -Tf -- "$rotated" "$log"
    rotated=
    trap - EXIT INT TERM
  fi
fi

exec /usr/bin/python3 "$script_dir/ensure_forward.py"
