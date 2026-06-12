#!/usr/bin/env bash
# One-command launcher for the TraceFlix-AIOps React + FastAPI dashboard.
#
#   bash scripts/run_webui.sh            # production: build SPA, serve all on one port
#   bash scripts/run_webui.sh --dev      # development: backend + Vite hot-reload (2 procs)
#   PORT=8080 bash scripts/run_webui.sh  # override backend port (default 8000)
#
# Works from any directory; resolves the aiops root itself.
set -euo pipefail
cd "$(dirname "$0")/.."                       # -> aiops/
ROOT="$(pwd)"
PORT="${PORT:-8000}"
DEV=0
[ "${1:-}" = "--dev" ] && DEV=1

# --- resolve a Python interpreter (name differs across shells) ---
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for c in python python3 py; do command -v "$c" >/dev/null 2>&1 && { PYTHON="$c"; break; }; done
fi
[ -n "$PYTHON" ] || { echo "ERROR: no Python interpreter found (python/python3/py)." >&2; exit 1; }

# --- prerequisites ---
command -v node >/dev/null 2>&1 || { echo "ERROR: node not found on PATH." >&2; exit 1; }
command -v npm  >/dev/null 2>&1 || { echo "ERROR: npm not found on PATH." >&2; exit 1; }

# --- backend deps ---
if ! "$PYTHON" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  echo "[*] Installing backend deps (fastapi, uvicorn)..."
  "$PYTHON" -m pip install -q -r requirements.txt
fi

# --- frontend deps ---
if [ ! -d webui/frontend/node_modules ]; then
  echo "[*] Installing frontend deps (npm install)..."
  ( cd webui/frontend && npm install --no-audit --no-fund )
fi

if [ "$DEV" -eq 1 ]; then
  echo "[*] DEV mode — backend :$PORT  +  Vite hot-reload :5173"
  "$PYTHON" -m uvicorn webui.backend.app:app --reload --port "$PORT" &
  BACK=$!
  ( cd webui/frontend && npm run dev ) &
  FRONT=$!
  trap 'echo; echo "[*] stopping..."; kill "$BACK" "$FRONT" 2>/dev/null || true' INT TERM EXIT
  echo "[*] Open http://localhost:5173   (API on :$PORT, proxied via /api)"
  wait
else
  echo "[*] PROD mode — building SPA, then serving everything on one port"
  ( cd webui/frontend && npm run build )
  echo
  echo "[*] Open  http://localhost:$PORT"
  exec "$PYTHON" -m uvicorn webui.backend.app:app --port "$PORT"
fi
