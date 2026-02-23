#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "[1/6] Checking Python 3.10+ ..."
python3 - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10+ is required")
print(f"Python OK: {sys.version.split()[0]}")
PY

echo "[2/6] Installing cb-memory package ..."
python3 -m pip install -e .

if [[ ! -f .env ]]; then
  echo "[3/6] Creating .env from .env.example ..."
  cp .env.example .env
else
  echo "[3/6] Reusing existing .env ..."
fi

echo "[4/6] Verifying Couchbase REST API ..."
if ! curl -sf "http://127.0.0.1:8091/pools" > /dev/null; then
  echo "Couchbase is not reachable on http://127.0.0.1:8091."
  echo "Install/start Couchbase Server locally, then re-run this script."
  exit 1
fi

echo "[5/6] Running Docker-free bootstrap ..."
cb-memory init

echo "[6/6] Done."
echo "Next: start MCP server with: python -m cb_memory.server"
