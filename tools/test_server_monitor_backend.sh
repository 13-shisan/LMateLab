#!/usr/bin/env bash
set -Eeuo pipefail

if (( $# == 0 )); then
  printf 'usage: %s <pytest-selector> [pytest-args...]\n' "${0##*/}" >&2
  exit 2
fi

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

if command -v cygpath >/dev/null 2>&1; then
  ROOT="$(cygpath -w "$ROOT")"
  export MSYS_NO_PATHCONV=1
fi

docker run --rm \
  -e JWT_SECRET=test-only-server-monitor-secret \
  -e LMATELAB_DATA_DIR=/tmp/lmatelab-test-var \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -v lmatelab_server_monitor_test_pip:/root/.cache/pip \
  -v "$ROOT/backend:/app:ro" \
  -w /app \
  python:3.12-slim-bookworm \
  sh -lc 'pip install -q -r requirements-server-monitor-test.txt && exec python -m pytest -q -p no:cacheprovider "$@"' sh "$@"
