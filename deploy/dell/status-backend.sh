#!/usr/bin/env bash
set -euo pipefail

root=${LMATELAB_DELL_ROOT:-$HOME/apps/lmatelab-dell}
port=${LMATELAB_PORT:-18755}
for name in backend agent-worker; do
  pid_file="$root/runtime/pids/$name.pid"
  if [[ -s "$pid_file" ]] && kill -0 "$(<"$pid_file")" 2>/dev/null; then
    printf '%s running pid=%s\n' "$name" "$(<"$pid_file")"
  else
    printf '%s stopped\n' "$name"
  fi
done
curl -fsS "http://127.0.0.1:$port/api/health/ready" || true
printf '\n'
