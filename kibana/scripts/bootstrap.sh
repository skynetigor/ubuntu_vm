#!/usr/bin/env bash
set -euo pipefail

KIBANA_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ -f "$KIBANA_DIR/.env" ]; then
  set -a; source "$KIBANA_DIR/.env"; set +a
fi

KIBANA_SRC="${KIBANA_SRC:-$KIBANA_DIR/src}"
COMMIT_FILE="$KIBANA_SRC/.bootstrapcommit"

if [ ! -d "$KIBANA_SRC" ]; then
  echo "ERROR: source directory not found: $KIBANA_SRC — run clone.sh first"
  exit 1
fi

CURRENT_COMMIT=$(git -C "$KIBANA_SRC" rev-parse HEAD)
STORED_COMMIT=$(cat "$COMMIT_FILE" 2>/dev/null || echo "")

# Workflow steps read the result from $STEP_OUTPUT; plain shell runs ignore it.
report_status() {
  if [ -n "${STEP_OUTPUT:-}" ]; then
    printf '{"status":"%s","commit":"%s"}' "$1" "$CURRENT_COMMIT" > "$STEP_OUTPUT"
  fi
}

if [ "$CURRENT_COMMIT" = "$STORED_COMMIT" ]; then
  echo "=== Skipping bootstrap — already at $CURRENT_COMMIT ==="
  report_status skipped
  exit 0
fi

cd "$KIBANA_SRC"

# Optional per-commit node_modules cache (BOOTSTRAP_CACHE_ROOT, e.g. /opt/kibana-cache).
CACHE_DIR="${BOOTSTRAP_CACHE_ROOT:+$BOOTSTRAP_CACHE_ROOT/$CURRENT_COMMIT}"
# A real node_modules directory cannot be replaced by a symlink without deleting it first.
if [ -n "$CACHE_DIR" ] && [ -d "$CACHE_DIR/node_modules" ] && { [ ! -e node_modules ] || [ -L node_modules ]; }; then
  echo "=== Cache hit — symlinking node_modules ($CURRENT_COMMIT) ==="
  ln -sfn "$CACHE_DIR/node_modules" node_modules
  report_status cache_linked
  exit 0
fi

# Bootstrapping through a symlink would rewrite another commit's cached node_modules.
if [ -L node_modules ]; then
  rm node_modules
fi

# ── Node version ──────────────────────────────────────────────────────────────
# set +u: nvm.sh uses unbound variables internally
# shellcheck disable=SC1091
set +u; source "${NVM_DIR:-/home/kibana/.nvm}/nvm.sh"; set -u
nvm install
nvm use

# ── pnpm ──────────────────────────────────────────────────────────────────────
PNPM_VERSION=$(node -e "
  try {
    const e = require('$KIBANA_SRC/package.json').engines;
    console.log((e && e.pnpm || '').replace(/^[~^>=<]+/, '').split(' ')[0]);
  } catch(e) {}
" 2>/dev/null || echo "")
PNPM_INSTALL_SPEC="${PNPM_VERSION:-latest}"

if ! command -v pnpm &>/dev/null; then
  echo "=== Installing pnpm@${PNPM_INSTALL_SPEC} ==="
  npm install -g "pnpm@${PNPM_INSTALL_SPEC}"
else
  echo "=== pnpm $(pnpm --version) already installed ==="
fi

# ── Bootstrap ─────────────────────────────────────────────────────────────────
# When running as root, wrap the package manager so kbn subcommands get --allow-root.
source "$(dirname "$0")/setup-root.sh"

echo "=== Bootstrapping ==="
KBN_BOOTSTRAP_NO_PREBUILT=true pnpm kbn bootstrap

# ── Pre-populate platform node binaries (required by the build tasks) ─────────
NODE_VERSION=$(cat .nvmrc)
echo "=== Checking Node binaries (${NODE_VERSION}) ==="

# darwin-arm64: reuse NVM's already-extracted copy if available
if [ -d ".node_binaries/${NODE_VERSION}/default/darwin-arm64/extract" ]; then
  echo "  skipping darwin-arm64 — already present"
elif [ -d "${NVM_DIR}/versions/node/v${NODE_VERSION}" ]; then
  echo "  copying darwin-arm64 from NVM..."
  for VARIANT in default glibc-217; do
    mkdir -p ".node_binaries/${NODE_VERSION}/${VARIANT}/darwin-arm64/extract"
    cp -r "${NVM_DIR}/versions/node/v${NODE_VERSION}/." \
      ".node_binaries/${NODE_VERSION}/${VARIANT}/darwin-arm64/extract/"
  done
else
  TARBALL="node-v${NODE_VERSION}-darwin-arm64.tar.gz"
  echo "  downloading darwin-arm64..."
  curl -fL "https://nodejs.org/dist/v${NODE_VERSION}/${TARBALL}" -o "/tmp/${TARBALL}"
  for VARIANT in default glibc-217; do
    mkdir -p ".node_binaries/${NODE_VERSION}/${VARIANT}/darwin-arm64/extract"
    tar xzf "/tmp/${TARBALL}" \
      -C ".node_binaries/${NODE_VERSION}/${VARIANT}/darwin-arm64/extract" \
      --strip-components=1
  done
  rm "/tmp/${TARBALL}"
fi

# linux-x64: NVM on Mac doesn't have this, always download
if [ -d ".node_binaries/${NODE_VERSION}/default/linux-x64/extract" ]; then
  echo "  skipping linux-x64 — already present"
else
  TARBALL="node-v${NODE_VERSION}-linux-x64.tar.gz"
  echo "  downloading linux-x64..."
  curl -fL "https://nodejs.org/dist/v${NODE_VERSION}/${TARBALL}" -o "/tmp/${TARBALL}"
  for VARIANT in default glibc-217; do
    mkdir -p ".node_binaries/${NODE_VERSION}/${VARIANT}/linux-x64/extract"
    tar xzf "/tmp/${TARBALL}" \
      -C ".node_binaries/${NODE_VERSION}/${VARIANT}/linux-x64/extract" \
      --strip-components=1
  done
  rm "/tmp/${TARBALL}"
fi

echo "$CURRENT_COMMIT" > "$COMMIT_FILE"
if [ -n "$CACHE_DIR" ] && [ ! -d "$CACHE_DIR/node_modules" ] && [ -d node_modules ] && [ ! -L node_modules ]; then
  mkdir -p "$CACHE_DIR"
  cp -al node_modules "$CACHE_DIR/node_modules"
  echo "=== Cached node_modules for $CURRENT_COMMIT ==="
fi
report_status bootstrapped
echo "=== Bootstrap done at $CURRENT_COMMIT ==="
