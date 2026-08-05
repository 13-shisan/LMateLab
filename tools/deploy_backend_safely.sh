#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
CANONICAL_PROJECT_DIR="$(cd "${LMATELAB_PROJECT_DIR:-/home/software/LMateLab}" && pwd -P)"

if [[ "$SCRIPT_PROJECT_DIR" != "$CANONICAL_PROJECT_DIR" ]]; then
    echo "deploy_backend_safely.sh must run from canonical production checkout: $CANONICAL_PROJECT_DIR" >&2
    exit 2
fi

PROJECT_DIR="$CANONICAL_PROJECT_DIR"
if [[ "${1:-}" == "--check-root-only" ]]; then
    echo "canonical_project_dir=$PROJECT_DIR"
    exit 0
fi

COMPOSE_FILE="$PROJECT_DIR/docker-compose.prod.yml"
COMPOSE=(docker compose -p lmatelab -f "$COMPOSE_FILE")
IMAGE_VALIDATOR="$PROJECT_DIR/tools/verify_backend_image.sh"
BUILD_TRANSACTION="$PROJECT_DIR/tools/build_python_images_safely.sh"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$PROJECT_DIR/var/backups/predeploy-$TIMESTAMP"
SERVICES=(backend worker beat)
declare -A OLD_IMAGES=()
declare -A ROLLBACK_TAGS=()
declare -A ROLLBACK_IMAGES=()
ROLLBACK_IMAGE_ARGS=()
DEPLOY_STARTED=0

cd "$PROJECT_DIR"

rollback() {
    local exit_code=$?
    local rollback_failed=0
    trap - ERR

    if [[ "$DEPLOY_STARTED" == "1" ]]; then
        echo "Deployment failed; restoring previous service images" >&2
        if ! /bin/bash "$BUILD_TRANSACTION" --restore-only "${ROLLBACK_IMAGE_ARGS[@]}"; then
            rollback_failed=1
        fi
        for service in worker beat backend; do
            if ! "${COMPOSE[@]}" up -d --no-deps --force-recreate "$service"; then
                rollback_failed=1
            fi
        done

        if ! wait_for_backend_health; then
            rollback_failed=1
        fi
        for service in "${SERVICES[@]}"; do
            if [[ "$(docker inspect --format '{{.State.Running}}' "lmatelab-$service-1" 2>/dev/null || true)" != "true" ]]; then
                rollback_failed=1
            fi
        done

        if [[ "$rollback_failed" == "1" ]]; then
            echo "CRITICAL: automatic rollback could not be verified" >&2
            exit 70
        fi
        echo "Rollback verified; previous service images are running" >&2
    fi

    exit "$exit_code"
}
trap rollback ERR

wait_for_backend_health() {
    local status

    for _ in $(seq 1 60); do
        status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' lmatelab-backend-1)"
        case "$status" in
            healthy)
                return 0
                ;;
            unhealthy)
                docker logs --tail 120 lmatelab-backend-1 >&2 || true
                return 1
                ;;
        esac
        sleep 2
    done

    echo "Backend did not become healthy within 120 seconds" >&2
    docker logs --tail 120 lmatelab-backend-1 >&2 || true
    return 1
}

echo "[1/6] Preflight"
"${COMPOSE[@]}" config -q
rollback_probe_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 \
    'https://matflow.top/api/academic-reports?page=1&page_size=1')"
[[ "$rollback_probe_code" == "200" ]]
python -m unittest backend.tests.test_compose_integrity -v
python -m unittest backend.tests.test_docker_context_integrity -v
python -m unittest backend.tests.test_deploy_script_integrity -v
docker run --rm \
    -e JWT_SECRET=test-only-secret \
    -e LMATELAB_DATA_DIR=/tmp/lmatelab-test-var \
    -e DATABASE_URL=sqlite:////tmp/lmatelab-test-eln.db \
    -e DIGEST_DATABASE_URL=sqlite:////tmp/lmatelab-test-digests.db \
    -v "$PROJECT_DIR/backend:/app" \
    -w /app \
    lmatelab-backend \
    python -m unittest tests.test_route_integrity -v

echo "[2/6] Consistent SQLite backup"
mkdir -p "$BACKUP_DIR"
python3 - "$PROJECT_DIR/var/db" "$BACKUP_DIR" <<'PY'
import sqlite3
import sys
from pathlib import Path

source_dir = Path(sys.argv[1])
backup_dir = Path(sys.argv[2])

for name in ("eln.db", "digests.db"):
    source_path = source_dir / name
    backup_path = backup_dir / name
    if not source_path.is_file():
        raise SystemExit(f"database is not a file: {source_path}")

    source = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    destination = sqlite3.connect(backup_path)
    try:
        source.backup(destination)
    finally:
        destination.close()
        source.close()

print(f"SQLite backup created at {backup_dir}")
PY

echo "[3/6] Preserve current service images"
for service in "${SERVICES[@]}"; do
    OLD_IMAGES[$service]="$(docker inspect --format '{{.Image}}' "lmatelab-$service-1")"
    ROLLBACK_TAGS[$service]="lmatelab-$service:rollback-$TIMESTAMP"
    docker image inspect "${OLD_IMAGES[$service]}" >/dev/null
    if [[ "$service" != "backend" ]]; then
        docker image tag "${OLD_IMAGES[$service]}" "${ROLLBACK_TAGS[$service]}"
        ROLLBACK_IMAGES[$service]="${OLD_IMAGES[$service]}"
    fi
done

rollback_tag="${ROLLBACK_TAGS[backend]}"
if /bin/bash "$IMAGE_VALIDATOR" "${OLD_IMAGES[backend]}" >/dev/null 2>&1; then
    docker image tag "${OLD_IMAGES[backend]}" "$rollback_tag"
else
    printf 'FROM %s\nCOPY healthcheck.py /app/healthcheck.py\n' \
        "${OLD_IMAGES[backend]}" |
        docker build --pull=false --tag "$rollback_tag" --file - "$PROJECT_DIR/backend"
fi
/bin/bash "$IMAGE_VALIDATOR" "$rollback_tag"
ROLLBACK_IMAGES[backend]="$(docker image inspect --format '{{.Id}}' "$rollback_tag")"
for service in "${SERVICES[@]}"; do
    ROLLBACK_IMAGE_ARGS+=("$service=${ROLLBACK_IMAGES[$service]}")
done

echo "[4/6] Build and recreate Python services"
/bin/bash "$BUILD_TRANSACTION" "${ROLLBACK_IMAGE_ARGS[@]}"
DEPLOY_STARTED=1
for service in worker beat backend; do
    "${COMPOSE[@]}" up -d --no-deps --force-recreate "$service"
done

echo "[5/6] Verify containers and application"
wait_for_backend_health
docker exec lmatelab-backend-1 python -c \
    "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4000/api/health/live', timeout=5)"
docker exec lmatelab-backend-1 python -c \
    'from routers.server_monitor import refresh_users_overview_cache; [refresh_users_overview_cache(days) for days in (7, 30, 90, 365)]'

route_output="$(docker exec lmatelab-backend-1 python -c \
    'from main import app; count=sum(1 for route in app.routes if getattr(route, "path", None) == "/api/db/vasp/cp_keys" and "GET" in (getattr(route, "methods", set()) or set())); print(f"ROUTE_COUNT={count}")')"
route_count="$(printf '%s\n' "$route_output" | sed -n 's/^ROUTE_COUNT=//p' | tail -n 1)"
[[ "$route_count" == "1" ]]

docker exec lmatelab-beat-1 test -f /app/var/db/eln.db
docker exec lmatelab-beat-1 test -f /app/var/db/digests.db
for service in "${SERVICES[@]}"; do
    docker exec "lmatelab-$service-1" test ! -f /app/.env
done

http_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 https://matflow.top)"
[[ "$http_code" == "200" ]]
password_policy_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 20 \
    https://matflow.top/api/auth/password-policy)"
[[ "$password_policy_code" == "200" ]]

echo "[6/6] Deployment verified"
trap - ERR
printf 'backend_image=%s\nrollback_tag=%s\nbackup_dir=%s\nmatflow_http=%s\n' \
    "$(docker inspect --format '{{.Image}}' lmatelab-backend-1)" \
    "${ROLLBACK_TAGS[backend]}" \
    "$BACKUP_DIR" \
    "$http_code"
