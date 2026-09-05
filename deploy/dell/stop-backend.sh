#!/usr/bin/env bash
set -euo pipefail

root=${LMATELAB_DELL_ROOT:-$HOME/apps/lmatelab-dell}
for name in agent-worker backend; do
  pid_file="$root/runtime/pids/$name.pid"
  [[ -s "$pid_file" ]] || continue
  pid=$(<"$pid_file")
  if [[ "$pid" =~ ^[0-9]+$ ]] && [[ -r "/proc/$pid/cmdline" ]]; then
    cmd=$(tr '\0' ' ' <"/proc/$pid/cmdline")
    if [[ "$cmd" == *"$root/"* ]] || [[ "$cmd" == *"main_107cup:app"* ]] || [[ "$cmd" == *"services.competition_agent.worker"* ]]; then
      kill "$pid"
      for _ in $(seq 1 10); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.5
      done
    else
      printf 'refusing to stop unexpected pid %s: %s\n' "$pid" "$cmd" >&2
      exit 2
    fi
  fi
  rm -f "$pid_file"
done
printf 'LMateLab backend stopped\n'
