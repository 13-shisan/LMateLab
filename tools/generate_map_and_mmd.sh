#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

log() { echo "[generate] $*"; }

log "Project root: $ROOT"
log "Step 1/4: export fastapi routes (backend/tools/export_fastapi_routes.py)"
(
  cd "$ROOT/backend"
  python tools/export_fastapi_routes.py
)

log "Step 2/4: export react routes (frontend/tools/export_react_routes.mjs)"
(
  cd "$ROOT/frontend"
  node tools/export_react_routes.mjs
)

log "Step 3/4: scan frontend api calls (frontend/tools/scan_api_calls.mjs)"
(
  cd "$ROOT/frontend"
  node tools/scan_api_calls.mjs
)

log "Step 4/4: export react routes (frontend/tools/build_page_backend_map_with_imports.mjs)"
(
  cd "$ROOT/frontend"
  node tools/build_page_backend_map_with_imports.mjs
)


log "Done. Outputs:"
log "  $ROOT/artifacts/backend_routes.json"
log "  $ROOT/artifacts/frontend_routes.json"
log "  $ROOT/artifacts/frontend_api_calls.json"
log "  $ROOT/artifacts/page_to_backend.json"
log "  $ROOT/artifacts/backend_to_pages.json"
log "  $ROOT/artifacts/graph.mmd"
