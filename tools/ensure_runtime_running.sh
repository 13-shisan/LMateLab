#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
CANONICAL_PROJECT_DIR="$(cd "${LMATELAB_PROJECT_DIR:-/home/software/LMateLab}" && pwd -P)"

if [[ "$SCRIPT_PROJECT_DIR" != "$CANONICAL_PROJECT_DIR" ]]; then
    echo "ensure_runtime_running.sh must run from canonical production checkout: $CANONICAL_PROJECT_DIR" >&2
    exit 2
fi

PROJECT_DIR="$CANONICAL_PROJECT_DIR"
if [[ "${1:-}" == "--check-root-only" ]]; then
    echo "canonical_project_dir=$PROJECT_DIR"
    exit 0
fi

COMPOSE_FILE="${LMATELAB_COMPOSE_FILE:-$PROJECT_DIR/docker-compose.prod.yml}"
BACKEND_ENV_FILE="${LMATELAB_BACKEND_ENV_FILE:-$PROJECT_DIR/backend/.env}"
DATA_DIR="${LMATELAB_DATA_DIR:-$PROJECT_DIR/var/data}"
ALLOWED_USERS_FILE="${LMATELAB_ALLOWED_USERS_FILE:-$DATA_DIR/allowed_users.json}"
NGINX_CONFIG="${LMATELAB_NGINX_CONFIG:-$PROJECT_DIR/nginx/default.conf}"
IMAGE_VALIDATOR="$PROJECT_DIR/tools/verify_backend_image.sh"
SSL_DIR="${LMATELAB_SSL_DIR:-/home/software/log-web/ssl/matflow.top}"
CERTIFICATE="$SSL_DIR/matflow.top.pem"
PRIVATE_KEY="$SSL_DIR/matflow.top.key"
LOCK_FILE="${LMATELAB_RUNTIME_LOCK_FILE:-/tmp/lmatelab-runtime-recovery.lock}"
MAX_ATTEMPTS="${LMATELAB_RUNTIME_MAX_ATTEMPTS:-60}"
RETRY_DELAY="${LMATELAB_RUNTIME_RETRY_DELAY:-5}"
RUNTIME_SERVICES=(redis backend worker beat nginx)
COMPOSE=(docker compose -p lmatelab -f "$COMPOSE_FILE")
LAST_REASON="not started"

if [[ ! "$MAX_ATTEMPTS" =~ ^[1-9][0-9]*$ ]]; then
    echo "LMATELAB_RUNTIME_MAX_ATTEMPTS must be a positive integer" >&2
    exit 2
fi
if [[ ! "$RETRY_DELAY" =~ ^[0-9]+$ ]]; then
    echo "LMATELAB_RUNTIME_RETRY_DELAY must be a non-negative integer" >&2
    exit 2
fi

log() {
    printf '[%s] %s\n' "$(date --iso-8601=seconds)" "$*" >&2
}

exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "another runtime recovery run already holds $LOCK_FILE"
    exit 0
fi

nfs_mount_ready() {
    local mount_point="$1" mount_info target filesystem

    mount_info="$(findmnt -rn -T "$mount_point" -o TARGET,FSTYPE 2>/dev/null || true)"
    read -r target filesystem <<<"$mount_info"
    [[ "$target" == "$mount_point" && "$filesystem" =~ ^nfs ]]
}

preflight_ready() {
    if ! nfs_mount_ready /home; then
        LAST_REASON="/home is not ready as an NFS mount"
        return 1
    fi
    if ! nfs_mount_ready /storage; then
        LAST_REASON="/storage is not ready as an NFS mount"
        return 1
    fi
    if [[ ! -f "$COMPOSE_FILE" ]]; then
        LAST_REASON="Compose file is not a regular file: $COMPOSE_FILE"
        return 1
    fi
    if [[ ! -f "$BACKEND_ENV_FILE" ]]; then
        LAST_REASON="backend environment file is not a regular file: $BACKEND_ENV_FILE"
        return 1
    fi
    if [[ ! -d "$DATA_DIR" ]]; then
        LAST_REASON="runtime data directory is not available: $DATA_DIR"
        return 1
    fi
    if [[ ! -f "$ALLOWED_USERS_FILE" ]]; then
        LAST_REASON="allowed-users config is not a regular file: $ALLOWED_USERS_FILE"
        return 1
    fi
    if [[ ! -f "$NGINX_CONFIG" ]]; then
        LAST_REASON="Nginx config is not a regular file: $NGINX_CONFIG"
        return 1
    fi
    if [[ ! -f "$IMAGE_VALIDATOR" ]]; then
        LAST_REASON="backend image validator is missing: $IMAGE_VALIDATOR"
        return 1
    fi
    if [[ ! -d "$SSL_DIR" ]]; then
        LAST_REASON="TLS directory is not available: $SSL_DIR"
        return 1
    fi
    if [[ ! -f "$CERTIFICATE" || ! -f "$PRIVATE_KEY" ]]; then
        LAST_REASON="TLS certificate or private key is missing under $SSL_DIR"
        return 1
    fi
    if ! docker info >/dev/null 2>&1; then
        LAST_REASON="Docker daemon is not ready"
        return 1
    fi
    if ! docker compose version >/dev/null 2>&1; then
        LAST_REASON="Docker Compose is not available"
        return 1
    fi
    if ! "${COMPOSE[@]}" config -q >/dev/null 2>&1; then
        LAST_REASON="Docker Compose configuration is not ready"
        return 1
    fi
    if ! /bin/bash "$IMAGE_VALIDATOR" >/dev/null 2>&1; then
        LAST_REASON="resolved backend image does not contain /app/healthcheck.py"
        return 1
    fi
}

service_container_id() {
    "${COMPOSE[@]}" ps -q "$1" 2>/dev/null || true
}

start_and_verify() {
    local service container_id running backend_id backend_health local_status

    if ! "${COMPOSE[@]}" up -d "${RUNTIME_SERVICES[@]}" >/dev/null; then
        LAST_REASON="Docker Compose could not start the production runtime"
        return 1
    fi

    for service in "${RUNTIME_SERVICES[@]}"; do
        container_id="$(service_container_id "$service")"
        if [[ -z "$container_id" ]]; then
            LAST_REASON="$service has no Compose container after startup"
            return 1
        fi
        running="$(docker inspect --format '{{.State.Running}}' "$container_id" 2>/dev/null || true)"
        if [[ "$running" != "true" ]]; then
            LAST_REASON="$service is not running after Compose startup"
            return 1
        fi
    done

    backend_id="$(service_container_id backend)"
    backend_health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}' "$backend_id" 2>/dev/null || true)"
    if [[ "$backend_health" != "healthy" ]]; then
        LAST_REASON="backend health is $backend_health"
        return 1
    fi

    if ! local_status="$(curl --silent --show-error --noproxy '*' --max-time 20 \
        --resolve matflow.top:443:127.0.0.1 \
        --output /dev/null --write-out '%{http_code}' \
        https://matflow.top/)"; then
        LAST_REASON="local HTTPS probe through Nginx failed"
        return 1
    fi
    if [[ "$local_status" != "200" && "$local_status" != "403" ]]; then
        LAST_REASON="local HTTPS probe returned unexpected status $local_status"
        return 1
    fi

    if ! curl --fail --silent --show-error --noproxy '*' --max-time 20 \
        https://matflow.top/ -o /dev/null; then
        LAST_REASON="public HTTPS probe failed"
        return 1
    fi
}

diagnose() {
    log "runtime state diagnostics follow"
    "${COMPOSE[@]}" ps >&2 2>/dev/null || true
}

cd "$PROJECT_DIR"
for ((attempt = 1; attempt <= MAX_ATTEMPTS; attempt++)); do
    if preflight_ready && start_and_verify; then
        log "production runtime recovery verified on attempt $attempt"
        exit 0
    fi

    log "attempt $attempt/$MAX_ATTEMPTS: $LAST_REASON"
    if ((attempt < MAX_ATTEMPTS)); then
        sleep "$RETRY_DELAY"
    fi
done

diagnose
log "production runtime recovery failed after $MAX_ATTEMPTS attempts"
exit 1
