#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

wait_for_url() {
  local url="$1"
  local timeout_seconds="$2"
  local start
  start="$(date +%s)"
  while ! curl -sf "$url" > /dev/null; do
    if (( $(date +%s) - start >= timeout_seconds )); then
      return 1
    fi
    sleep 2
  done
}

check_command() {
  command -v "$1" >/dev/null 2>&1
}

echo "=========================================="
echo "cb-memory Complete Bootstrap (macOS)"
echo "=========================================="
echo ""

# Step 1: Install Homebrew if not present
echo "[1/11] Checking Homebrew ..."
if ! check_command brew; then
  echo "Homebrew not found. Installing Homebrew..."
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  
  # Add Homebrew to PATH for current session
  if [[ -f /opt/homebrew/bin/brew ]]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
  elif [[ -f /usr/local/bin/brew ]]; then
    eval "$(/usr/local/bin/brew shellenv)"
  fi
  echo "Homebrew installed."
else
  echo "Homebrew OK."
fi

# Step 2: Check Python 3.10+ (avoid replacing system Python)
echo "[2/11] Checking Python 3.10+ ..."
if check_command python3 && python3 --version | grep -qE "Python (3\.(1[0-9]|[2-9][0-9])|[4-9]\.|\d{2,}\.)"; then
  PYTHON_VERSION=$(python3 --version)
  PYTHON_BIN="python3"
  echo "Python OK: $PYTHON_VERSION using $PYTHON_BIN"
else
  echo "Python 3.10+ not found."
  echo ""
  echo "Your Python version is: $(python3 --version 2>/dev/null || echo 'not found')"
  echo ""
  echo "To install Python 3.10+ without conflicts, use pyenv:"
  echo "  1. brew install pyenv"
  echo "  2. pyenv install 3.11"
  echo "  3. pyenv global 3.11"
  echo "  4. Then re-run this script"
  echo ""
  echo "Or install a newer Python and ensure it's in your PATH before system Python."
  exit 1
fi

# Step 3: Install Python pip and upgrade
echo "[3/11] Ensuring pip is up to date ..."
$PYTHON_BIN -m pip install --upgrade pip --quiet

# Step 4: Install Docker Desktop if needed
echo "[4/11] Checking Docker ..."
if check_command docker && docker info >/dev/null 2>&1; then
  echo "Docker OK."
else
  echo "Docker not installed or not running."
  echo "Please install Docker Desktop from: https://docs.docker.com/desktop/install/mac-install/"
  echo "After installation, start Docker Desktop and run this script again."
  exit 1
fi

# Step 5: Install cb-memory Python package
echo "[5/11] Installing cb-memory package ..."
if [[ ! -f pyproject.toml ]]; then
  echo "Error: pyproject.toml not found. Are you in the correct directory?"
  exit 1
fi
$PYTHON_BIN -m pip install -e . --quiet

# Step 6: Create .env if needed
if [[ ! -f .env ]]; then
  echo "[6/11] Creating .env from .env.example ..."
  cp .env.example .env
else
  echo "[6/11] Reusing existing .env ..."
fi

# Step 7: Ensure Couchbase is running via Docker
echo "[7/11] Ensuring Couchbase is reachable ..."
if ! curl -sf "http://127.0.0.1:8091/pools" > /dev/null; then
  echo "Couchbase not reachable. Starting Couchbase via Docker..."
  docker rm -f cb >/dev/null 2>&1 || true
  docker run -d \
    --name cb \
    -p 8091-8094:8091-8094 \
    -p 11210-11211:11210-11211 \
    -v cb-data:/opt/couchbase/var \
    couchbase:community
  
  echo "Waiting for Couchbase to start..."
  if ! wait_for_url "http://127.0.0.1:8091/pools" 180; then
    echo "Couchbase failed to become ready."
    echo "Check logs: docker logs cb"
    exit 1
  fi
  echo "Couchbase is ready."
else
  echo "Couchbase OK."
fi

# Step 8: Install Ollama via Homebrew if not present
echo "[8/11] Checking Ollama ..."
if ! check_command ollama; then
  echo "Ollama not found. Installing via Homebrew..."
  brew install ollama --quiet
else
  echo "Ollama OK."
fi

# Step 9: Ensure Ollama server is running
if ! curl -sf "http://127.0.0.1:11434/api/tags" > /dev/null; then
  echo "Starting Ollama server..."
  nohup ollama serve >/tmp/ollama-cb-memory.log 2>&1 &
  if ! wait_for_url "http://127.0.0.1:11434/api/tags" 60; then
    echo "Ollama server failed to start."
    echo "Check logs: /tmp/ollama-cb-memory.log"
    exit 1
  fi
  echo "Ollama server is ready."
else
  echo "Ollama server OK."
fi

# Step 10: Pull embedding model
echo "[10/11] Ensuring nomic-embed-text model is available..."
if ! ollama list | grep -q nomic-embed-text; then
  echo "Downloading nomic-embed-text model..."
  ollama pull nomic-embed-text
else
  echo "nomic-embed-text model OK."
fi

echo "[11/11] Running cb-memory installer (Factory MCP + bootstrap) ..."
$PYTHON_BIN -m cb_memory.cli.main install \
  --ide factory \
  --non-interactive \
  --cb-connection-string couchbase://localhost \
  --cb-username Administrator \
  --cb-password password \
  --cb-bucket coding-memory \
  --project-id "$ROOT_DIR" \
  --ollama-host http://localhost:11434 \
  --ollama-embedding-model nomic-embed-text \
  --write-env \
  --bootstrap

echo ""
echo "=========================================="
echo "Bootstrap Complete!"
echo "=========================================="
echo ""
echo "All systems up:"
echo "  - Python 3.10+"
echo "  - Docker + Couchbase"
echo "  - Ollama (nomic-embed-text)"
echo "  - cb-memory package"
echo "  - Factory MCP configured"
echo "  - Database provisioned"
echo "  - Chat import enabled"
echo ""
echo "Next steps:"
echo "  1. Restart your IDE to load MCP tools"
echo "  2. Test: $PYTHON_BIN -m cb_memory.cli.main stats"
echo ""
echo "For manual management:"
echo "  - Stop Couchbase: docker stop cb"
echo "  - Start Couchbase: docker start cb"
echo "  - Stop Ollama: pkill ollama"
echo "  - Start Ollama: ollama serve"
echo ""
