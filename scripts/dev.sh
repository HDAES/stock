#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_UVICORN="$ROOT_DIR/.venv/bin/uvicorn"

if [[ ! -x "$VENV_UVICORN" ]]; then
  echo "Missing .venv or uvicorn. Run setup first:"
  echo "  python3 -m venv .venv"
  echo "  source .venv/bin/activate"
  echo "  pip install -e \".[dev]\""
  exit 1
fi

if [[ ! -d "$ROOT_DIR/frontend/node_modules" ]]; then
  echo "Missing frontend/node_modules. Run setup first:"
  echo "  npm --prefix frontend install"
  exit 1
fi

cleanup() {
  if [[ -n "${API_PID:-}" ]] && kill -0 "$API_PID" 2>/dev/null; then
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

cd "$ROOT_DIR"
"$VENV_UVICORN" stock_quant.web.api:app --reload --host 127.0.0.1 --port 8000 &
API_PID=$!

echo "API: http://127.0.0.1:8000"
echo "Web: http://127.0.0.1:5173"

npm --prefix frontend run dev
