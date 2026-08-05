#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
CANONICAL_PROJECT_DIR="$(cd "${LMATELAB_PROJECT_DIR:-/home/software/LMateLab}" && pwd -P)"

if [[ "$SCRIPT_PROJECT_DIR" != "$CANONICAL_PROJECT_DIR" ]]; then
    echo "verify_backend_image.sh must run from canonical production checkout: $CANONICAL_PROJECT_DIR" >&2
    exit 2
fi

PROJECT_DIR="$CANONICAL_PROJECT_DIR"
COMPOSE_FILE="${LMATELAB_COMPOSE_FILE:-$PROJECT_DIR/docker-compose.prod.yml}"
COMPOSE=(docker compose -p lmatelab -f "$COMPOSE_FILE")
BACKEND_IMAGE="${1:-${LMATELAB_BACKEND_IMAGE:-}}"

if [[ -z "$BACKEND_IMAGE" ]]; then
    BACKEND_IMAGE="$(
        "${COMPOSE[@]}" config --format json |
            python3 -c 'import json, sys; service=json.load(sys.stdin)["services"]["backend"]; print(service.get("image") or "lmatelab-backend")'
    )"
fi
if [[ -z "$BACKEND_IMAGE" ]]; then
    echo "resolved backend image name is empty" >&2
    exit 1
fi

docker image inspect "$BACKEND_IMAGE" >/dev/null
docker run --rm --pull never --entrypoint test \
    "$BACKEND_IMAGE" -f /app/healthcheck.py
printf 'verified_backend_image=%s\n' "$BACKEND_IMAGE"
