#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Load .env from the script's directory
if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

KIBANA_FORK="${KIBANA_FORK:-https://github.com/elastic/kibana}"
KIBANA_BRANCH="${KIBANA_BRANCH:-main}"
LOCAL_DIR="${LOCAL_DIR:-dist}"

SRC_DIR="$SCRIPT_DIR/$LOCAL_DIR/kibana/src"
OUT_DIR="$SCRIPT_DIR/$LOCAL_DIR/kibana/dist"

echo "=== Kibana Local Build ==="
echo "  Fork  : $KIBANA_FORK"
echo "  Branch: $KIBANA_BRANCH"
echo "  Output: $OUT_DIR"
echo ""

# ── Clone ──────────────────────────────────────────────────────────────────────
if [ -d "$SRC_DIR" ]; then
  echo "=== Skipping clone — $SRC_DIR already exists ==="
else
  echo "=== Cloning ==="
  git clone --depth 1 --branch "$KIBANA_BRANCH" "$KIBANA_FORK" "$SRC_DIR"
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

# ── Build ─────────────────────────────────────────────────────────────────────
rm -rf build/
echo "=== Building ==="
node scripts/build \
  --skip-initialize \
  --skip-archives \
  --skip-os-packages \
  --skip-cloud-dependencies-download \
  --skip-cdn-assets

# ── Move dist to output dir ───────────────────────────────────────────────────
BUILD_DIR=$(ls -d build/default/kibana-*/ | head -1)
rm -rf "$OUT_DIR"
mkdir -p "$(dirname "$OUT_DIR")"
mv "$BUILD_DIR" "$OUT_DIR"

# Persist node version into .env so docker-compose can pass it as a build arg
# sed -i '' is BSD (macOS); GNU sed (Linux) uses sed -i — use a tmp file for portability
if grep -q "^NODE_VERSION=" "$SCRIPT_DIR/.env" 2>/dev/null; then
  tmp=$(mktemp)
  sed "s/^NODE_VERSION=.*/NODE_VERSION=${NODE_VERSION}/" "$SCRIPT_DIR/.env" > "$tmp"
  mv "$tmp" "$SCRIPT_DIR/.env"
else
  echo "NODE_VERSION=${NODE_VERSION}" >> "$SCRIPT_DIR/.env"
fi

# ── Clean up source ───────────────────────────────────────────────────────────
echo "=== Cleaning up source ==="
cd "$SCRIPT_DIR"
rm -rf "$SCRIPT_DIR/$LOCAL_DIR/kibana/src"

echo ""
echo "=== Done! Built Kibana at: $OUT_DIR ==="
