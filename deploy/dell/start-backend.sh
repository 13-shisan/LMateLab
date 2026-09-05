#!/usr/bin/env bash
set -euo pipefail

root=${LMATELAB_DELL_ROOT:-$HOME/apps/lmatelab-dell}
current=$(readlink -f "$root/current")
runtime="$root/runtime"
config="$root/config"
logs="$root/logs"

test -d "$current/source/backend"
test -x "$runtime/python312/bin/python"
test -f "$config/runtime.env"
test -s "$config/jwt.secret"
mkdir -p "$logs" "$runtime/pids"

for name in backend agent-worker; do
  pid_file="$runtime/pids/$name.pid"
  if [[ -s "$pid_file" ]] && kill -0 "$(<"$pid_file")" 2>/dev/null; then
    printf '%s is already running (pid %s)\n' "$name" "$(<"$pid_file")" >&2
    exit 2
  fi
done

set -a
# shellcheck source=/dev/null
source "$config/runtime.env"
set +a

export JWT_SECRET
JWT_SECRET=$(<"$config/jwt.secret")
if [[ "${LMATELAB_COMPETITION_AGENT_PROVIDER:-llm}" == "llm" ]]; then
  key_file=${LMATELAB_LLM_API_KEY_FILE:?configure LMATELAB_LLM_API_KEY_FILE}
  if [[ -e "$key_file" ]]; then
    test "$(stat -c '%a' "$key_file")" = "600"
  fi
fi

cd "$current/source/backend"
nohup "$runtime/python312/bin/python" -m uvicorn main_107cup:app \
  --host "${LMATELAB_BIND_HOST:-127.0.0.1}" --port "${LMATELAB_PORT:-18755}" \
  >"$logs/backend.out" 2>"$logs/backend.err" &
printf '%s\n' "$!" >"$runtime/pids/backend.pid"

nohup "$runtime/python312/bin/python" -m services.competition_agent.worker \
  --poll-seconds 1 --max-idle-cycles 10000 \
  >"$logs/agent-worker.out" 2>"$logs/agent-worker.err" &
printf '%s\n' "$!" >"$runtime/pids/agent-worker.pid"

for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${LMATELAB_PORT:-18755}/api/health/ready" >/dev/null; then
    printf 'LMateLab backend ready on 127.0.0.1:%s\n' "${LMATELAB_PORT:-18755}"
    exit 0
  fi
  sleep 1
done
printf 'backend did not become ready; inspect %s/backend.err\n' "$logs" >&2
exit 1
