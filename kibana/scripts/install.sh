#!/usr/bin/env bash
set -euo pipefail

OS=$(uname -s)   # Darwin | Linux
APT_UPDATED=false

ok()  { echo "  [ok] $*"; }
info(){ echo "  --> $*"; }

apt_install() {
  if [ "$APT_UPDATED" = false ]; then
    sudo apt-get update -q
    APT_UPDATED=true
  fi
  sudo apt-get install -y "$@"
}

echo "=== Checking dependencies ==="
echo "  Platform: $OS"
echo ""

# ── git ──────────────────────────────────────────────────────────────────────
if command -v git &>/dev/null; then
  ok "git $(git --version | awk '{print $3}')"
else
  info "installing git"
  if [ "$OS" = "Darwin" ]; then brew install git
  else apt_install git
  fi
fi

# ── curl ─────────────────────────────────────────────────────────────────────
if command -v curl &>/dev/null; then
  ok "curl $(curl --version | head -1 | awk '{print $2}')"
else
  info "installing curl"
  if [ "$OS" = "Darwin" ]; then brew install curl
  else apt_install curl
  fi
fi

# ── python3 (used by start-es.sh for JSON parsing) ───────────────────────────
if command -v python3 &>/dev/null; then
  ok "python3 $(python3 --version | awk '{print $2}')"
else
  info "installing python3"
  if [ "$OS" = "Darwin" ]; then brew install python3
  else apt_install python3
  fi
fi

# ── NVM ──────────────────────────────────────────────────────────────────────
NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
if [ -s "$NVM_DIR/nvm.sh" ]; then
  source "$NVM_DIR/nvm.sh"
  ok "nvm $(nvm --version)"
else
  info "installing nvm"
  NVM_INSTALL_VERSION="0.40.3"
  curl -fsSL "https://raw.githubusercontent.com/nvm-sh/nvm/v${NVM_INSTALL_VERSION}/install.sh" | bash
  source "$NVM_DIR/nvm.sh"
fi

# ── Node (version from .nvmrc if available, otherwise lts/*) ─────────────────
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
NVMRC="$SCRIPT_DIR/../dist/kibana/src/.nvmrc"
if [ -f "$NVMRC" ]; then
  NODE_VERSION=$(cat "$NVMRC")
  info "node version from .nvmrc: $NODE_VERSION"
  nvm install "$NODE_VERSION"
  nvm use "$NODE_VERSION"
else
  nvm install --lts
  nvm use --lts
fi
ok "node $(node --version)"

# ── yarn ─────────────────────────────────────────────────────────────────────
if command -v yarn &>/dev/null; then
  ok "yarn $(yarn --version)"
else
  info "installing yarn"
  npm install -g yarn
fi

# ── Docker ───────────────────────────────────────────────────────────────────
if command -v docker &>/dev/null; then
  ok "docker $(docker --version | awk '{print $3}' | tr -d ',')"
else
  info "installing docker"
  if [ "$OS" = "Darwin" ]; then
    echo "  ERROR: Docker Desktop must be installed manually on macOS: https://www.docker.com/products/docker-desktop/"
    exit 1
  else
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker "$USER"
    info "added $USER to docker group — re-login or run: newgrp docker"
  fi
fi

# ── docker compose (plugin, not standalone docker-compose) ───────────────────
if docker compose version &>/dev/null 2>&1; then
  ok "docker compose $(docker compose version --short 2>/dev/null || docker compose version | awk '{print $4}')"
else
  info "installing docker compose plugin"
  if [ "$OS" = "Darwin" ]; then
    echo "  ERROR: docker compose plugin comes with Docker Desktop on macOS"
    exit 1
  else
    apt_install docker-compose-plugin
  fi
fi

echo ""
echo "=== All dependencies satisfied ==="
