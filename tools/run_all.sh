#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

mkdir -p artifacts

node frontend/tools/export_react_routes.mjs > var/artifacts/frontend_routes.json
node frontend/tools/scan_api_calls.mjs > var/artifacts/frontend_api_calls.json
python backend/tools/export_fastapi_routes.py > var/artifacts/backend_routes.json

node tools/build_page_backend_map.mjs
echo "Wrote: artifacts/graph.mmd (or see tools/build_page_backend_map.mjs output settings)"
