#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
CANONICAL_PROJECT_DIR="$(cd "${LMATELAB_PROJECT_DIR:-/home/software/LMateLab}" && pwd -P)"

if [[ "$SCRIPT_PROJECT_DIR" != "$CANONICAL_PROJECT_DIR" ]]; then
    echo "build_python_images_safely.sh must run from canonical production checkout: $CANONICAL_PROJECT_DIR" >&2
    exit 2
fi

PROJECT_DIR="$CANONICAL_PROJECT_DIR"
COMPOSE_FILE="${LMATELAB_COMPOSE_FILE:-$PROJECT_DIR/docker-compose.prod.yml}"
IMAGE_VALIDATOR="${LMATELAB_IMAGE_VALIDATOR:-$PROJECT_DIR/tools/verify_backend_image.sh}"
COMPOSE=(docker compose -p lmatelab -f "$COMPOSE_FILE")
SERVICES=(backend worker beat)
declare -A ROLLBACK_IMAGES=()
RESTORE_ONLY=0

if [[ "${1:-}" == "--restore-only" ]]; then
    RESTORE_ONLY=1
    shift
fi
for assignment in "$@"; do
    service="${assignment%%=*}"
    image="${assignment#*=}"
    case "$service" in
        backend|worker|beat)
            [[ "$image" != "$assignment" && -n "$image" ]] || exit 2
            ROLLBACK_IMAGES[$service]="$image"
            ;;
        *)
            echo "unsupported service image assignment: $assignment" >&2
            exit 2
            ;;
    esac
done
for service in "${SERVICES[@]}"; do
    if [[ -z "${ROLLBACK_IMAGES[$service]:-}" ]]; then
        echo "missing rollback image for $service" >&2
        exit 2
    fi
done

restore_canonical_tags() {
    local service failed=0

    for service in "${SERVICES[@]}"; do
        if ! docker image tag "${ROLLBACK_IMAGES[$service]}" "lmatelab-$service:latest"; then
            failed=1
        fi
    done
    return "$failed"
}

restore_after_error() {
    local original_status=$?
    trap - ERR

    if ! restore_canonical_tags; then
        echo "CRITICAL: canonical service image tags could not be restored" >&2
        exit 70
    fi
    exit "$original_status"
}

if [[ "$RESTORE_ONLY" == "1" ]]; then
    if ! restore_canonical_tags; then
        echo "CRITICAL: canonical service image tags could not be restored" >&2
        exit 70
    fi
    exit 0
fi

trap restore_after_error ERR
cd "$PROJECT_DIR"
"${COMPOSE[@]}" build "${SERVICES[@]}"
/bin/bash "$IMAGE_VALIDATOR"
trap - ERR
