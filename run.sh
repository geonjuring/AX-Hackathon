#!/usr/bin/env bash
set -euo pipefail
APP_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
cd "$APP_DIR"
export SLP_DB="${SLP_DB:-$APP_DIR/slp.duckdb}"
export SLP_DATA="${SLP_DATA:-$APP_DIR/data}"
PYTHON="${SLP_PYTHON:-python}"
args=(run unified_app.py --server.address "${BIND_ADDRESS:-127.0.0.1}" --server.port "${PORT:-8501}" --server.headless true --browser.gatherUsageStats false)
if [[ -n "${BASE_PATH:-}" ]]; then args+=(--server.baseUrlPath "$BASE_PATH"); fi
exec "$PYTHON" -m streamlit "${args[@]}"
