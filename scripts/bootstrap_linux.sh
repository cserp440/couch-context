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

detect_package_manager() {
  if check_command apt-get; then
    echo "apt"
  elif check_command yum; then
    echo "yum"
  elif check_command dnf; then
    echo "dnf"
  elif check_command pacman; then
    echo "pacman"
  elif check_command zypper; then
    echo "zypper"
  else
    echo "unknown"
  fi
}

echo "=========================================="
echo "cb-memory Complete Bootstrap (Linux)"
echo "=========================================="
echo ""

# Step 1: Check Python 3.10+ (avoid replacing system Python)
echo "[1/11] Checking Python 3.10+ ..."
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
  echo "  1. curl https://pyenv.run | bash"
  echo "  2. Add pyenv to your shell (see output of step 1)"
  echo "  3. pyenv install 3.11"
  echo "  4. pyenv global 3.11"
  echo "  5. Then re-run this script"
  echo ""
  echo "Or install a newer Python using your package manager and ensure it's in PATH."
  echo "Visit: https://www.python.org/downloads/"
  exit 1
fi

# Step 2: Ensure pip is available and upgraded
echo "[2/11] Ensuring pip is available..."
$PYTHON_BIN -m pip install --upgrade pip --quiet || {
  echo "pip not available. Installing..."
  PKG_MANAGER=$(detect_package_manager)
  case "$PKG_MANAGER" in
    apt)
      sudo apt-get install -y python3-pip
      ;;
    yum|dnf)
      sudo yum install -y python3-pip || sudo dnf install -y python3-pip
      ;;
    pacman)
      sudo pacman -S --noconfirm python-pip
      ;;
    zypper)
      sudo zypper install -y python3-pip
      ;;
  esac
}
$PYTHON_BIN -m pip install --upgrade pip --quiet

# Step 3: Check Docker and install if needed
echo "[3/11] Checking Docker..."
if check_command docker && docker info >/dev/null 2>&1; then
  echo "Docker OK."
else
  echo "Docker not installed. Installing Docker..."
  
  if check_command apt-get; then
    # Install Docker on Debian/Ubuntu
    sudo apt-get update -qq
    sudo apt-get install -y ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update -qq
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io
  else
    echo "Please install Docker manually:"
    echo "  Visit: https://docs.docker.com/engine/install/"
    echo "  After installation, ensure your user is added to the 'docker' group:"
    echo "    sudo usermod -aG docker \$USER"
    echo "  Then log out and back in, or run this script with sudo: sudo $0"
    exit 1
  fi
  
  # Start Docker service
  sudo systemctl start docker || sudo service docker start
  sudo systemctl enable docker || echo "Docker installed, but may need manual start."
  echo "Docker installed."
fi

# Step 4: Ensure user can run Docker without sudo (if not root)
if [[ $EUID -ne 0 ]] && ! groups | grep -q docker; then
  echo "Warning: Your user is not in the 'docker' group."
  echo "To run Docker without sudo, run:"
  echo "  sudo usermod -aG docker \$USER"
  echo "Then log out and back in."
  # Try to run docker with sudo for this session
  alias docker='sudo docker'
fi

# Step 5: Install cb-memory package
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
DOCKER_CMD="docker"
if ! $DOCKER_CMD info >/dev/null 2>&1; then
  DOCKER_CMD="sudo docker"
fi

if ! curl -sf "http://127.0.0.1:8091/pools" > /dev/null; then
  echo "Couchbase not reachable. Starting Couchbase via Docker..."
  $DOCKER_CMD rm -f cb >/dev/null 2>&1 || true
  $DOCKER_CMD run -d \
    --name cb \
    -p 8091-8094:8091-8094 \
    -p 11210-11211:11210-11211 \
    -v cb-data:/opt/couchbase/var \
    couchbase:community
  
  echo "Waiting for Couchbase to start..."
  if ! wait_for_url "http://127.0.0.1:8091/pools" 180; then
    echo "Couchbase failed to become ready."
    echo "Check logs: $DOCKER_CMD logs cb"
    exit 1
  fi
  echo "Couchbase is ready."
else
  echo "Couchbase OK."
fi

# Step 8: Install Ollama
echo "[8/11] Checking Ollama..."
if check_command ollama; then
  echo "Ollama OK."
else
  echo "Ollama not found. Installing Ollama..."
  curl -fsSL https://ollama.com/install.sh | sh
  echo "Ollama installed."
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
echo "Note: If Docker was installed, you may need to log out and log back in"
echo "for Docker to work without sudo (if your user was added to docker group)."
