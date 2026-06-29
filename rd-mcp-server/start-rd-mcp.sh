#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export MCP_MOCK_HOST="${MCP_MOCK_HOST:-0.0.0.0}"
export MCP_MOCK_PORT="${MCP_MOCK_PORT:-8005}"
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"

exec "$SCRIPT_DIR/venv/bin/gunicorn" \
  -w "${WEB_CONCURRENCY:-1}" \
  -k uvicorn.workers.UvicornWorker \
  server:app \
  --bind "${MCP_MOCK_HOST}:${MCP_MOCK_PORT}" \
  --access-logfile - \
  --error-logfile -
