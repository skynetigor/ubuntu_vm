#!/usr/bin/env bash
set -euo pipefail

KIBANA_DIR="$(cd "$(dirname "$0")/.." && pwd)"

# Debug
echo Hello from bootstrap.sh

if [ -f "$KIBANA_DIR/.env" ]; then
  set -a; source "$KIBANA_DIR/.env"; set +a
fi

LOCAL_DIR="${LOCAL_DIR:-dist}"
SRC_DIR="$KIBANA_DIR/$LOCAL_DIR/kibana/src"
COMMIT_FILE="$KIBANA_DIR/$LOCAL_DIR/kibana/.bootstrapcommit"

if [ ! -d "$SRC_DIR" ]; then
  echo "ERROR: source directory not found: $SRC_DIR — run clone.sh first"
  exit 1
fi

CURRENT_COMMIT=$(git -C "$SRC_DIR" rev-parse HEAD)
STORED_COMMIT=$(cat "$COMMIT_FILE" 2>/dev/null || echo "")
if [ "$CURRENT_COMMIT" = "$STORED_COMMIT" ]; then
  echo "=== Skipping bootstrap — already at $CURRENT_COMMIT ==="
  exit 0
fi

cd "$SRC_DIR"

# ── Node version ──────────────────────────────────────────────────────────────
NVM_DIR="${NVM_DIR:-$HOME/.nvm}"
if [ -s "$NVM_DIR/nvm.sh" ]; then
  source "$NVM_DIR/nvm.sh"
  nvm install
  nvm use
fi

# ── Bootstrap ─────────────────────────────────────────────────────────────────
# When running as root, wrap yarn so all `kbn` subcommands get --allow-root.
source "$(dirname "$0")/setup-root.sh"

echo "=== Bootstrapping ==="
KBN_BOOTSTRAP_NO_PREBUILT=true yarn kbn bootstrap

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
echo "=== Bootstrap done at $CURRENT_COMMIT ==="
