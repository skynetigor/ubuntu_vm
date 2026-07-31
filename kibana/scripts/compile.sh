#!/usr/bin/env bash
set -euo pipefail

KIBANA_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ -f "$KIBANA_DIR/.env" ]; then
  set -a; source "$KIBANA_DIR/.env"; set +a
fi

LOCAL_DIR="${LOCAL_DIR:-dist}"
SRC_DIR="$KIBANA_DIR/$LOCAL_DIR/kibana/src"
OUT_DIR="$KIBANA_DIR/$LOCAL_DIR/kibana/dist"
COMMIT_FILE="$KIBANA_DIR/$LOCAL_DIR/kibana/.compilecommit"

if [ ! -d "$SRC_DIR" ]; then
  echo "ERROR: source directory not found: $SRC_DIR — run clone.sh and bootstrap.sh first"
  exit 1
fi

CURRENT_COMMIT=$(git -C "$SRC_DIR" rev-parse HEAD)
STORED_COMMIT=$(cat "$COMMIT_FILE" 2>/dev/null || echo "")
if [ "$CURRENT_COMMIT" = "$STORED_COMMIT" ]; then
  echo "=== Skipping compile — already at $CURRENT_COMMIT ==="
  # Still sync NODE_VERSION so docker-compose always has it (setup step wipes .env)
  _NV=$(cat "$SRC_DIR/.nvmrc" 2>/dev/null | tr -d '[:space:]')
  if [ -n "$_NV" ]; then
    if grep -q "^NODE_VERSION=" "$KIBANA_DIR/.env" 2>/dev/null; then
      tmp=$(mktemp)
      sed "s/^NODE_VERSION=.*/NODE_VERSION=${_NV}/" "$KIBANA_DIR/.env" > "$tmp"
      mv "$tmp" "$KIBANA_DIR/.env"
    else
      echo "NODE_VERSION=${_NV}" >> "$KIBANA_DIR/.env"
    fi
    echo "=== NODE_VERSION=${_NV} written to .env ==="
  fi
  exit 0
fi

cd "$SRC_DIR"

# ── Node version ──────────────────────────────────────────────────────────────
# set +u: nvm.sh uses unbound variables internally
# shellcheck disable=SC1091
set +u; source "${NVM_DIR:-/opt/nvm}/nvm.sh"; set -u
nvm install
nvm use
npm ls -g yarn --depth=0 2>/dev/null | grep -q yarn || npm install -g yarn

NODE_VERSION=$(cat .nvmrc)

# ── Build ─────────────────────────────────────────────────────────────────────
# When running as root, wrap yarn so all `kbn` subcommands spawned by the build
# (e.g. yarn kbn build-shared) get --allow-root automatically.
source "$(dirname "$0")/setup-root.sh"

rm -rf build/
echo "=== Building ==="
node scripts/build \
  --skip-initialize \
  --skip-archives \
  --skip-os-packages \
  --skip-cloud-dependencies-download \
  --skip-cdn-assets

# ── Move dist to output dir ───────────────────────────────────────────────────
# Pick the platform-matching directory (uname detects darwin vs linux, x64 vs arm64)
_BUILD_OS=$(uname -s | tr '[:upper:]' '[:lower:]')
_BUILD_ARCH=$(uname -m | sed 's/aarch64/arm64/;s/x86_64/x64/')
BUILD_DIR=$(ls -d "build/default/kibana-"*"-${_BUILD_OS}-${_BUILD_ARCH}/" 2>/dev/null | head -1)
if [ -z "$BUILD_DIR" ]; then
  # Fallback: first matching dir (legacy behaviour)
  BUILD_DIR=$(ls -d build/default/kibana-*/ 2>/dev/null | head -1)
fi
if [ -z "$BUILD_DIR" ]; then
  echo "ERROR: build output not found under build/default/ — the build may have failed"
  exit 1
fi
rm -rf "$OUT_DIR"
mkdir -p "$(dirname "$OUT_DIR")"
mv "$BUILD_DIR" "$OUT_DIR"

# ── Persist node version into .env so docker-compose can pass it as a build arg ─
# sed -i '' is BSD (macOS); GNU sed (Linux) uses sed -i — use a tmp file for portability
if grep -q "^NODE_VERSION=" "$KIBANA_DIR/.env" 2>/dev/null; then
  tmp=$(mktemp)
  sed "s/^NODE_VERSION=.*/NODE_VERSION=${NODE_VERSION}/" "$KIBANA_DIR/.env" > "$tmp"
  mv "$tmp" "$KIBANA_DIR/.env"
else
  echo "NODE_VERSION=${NODE_VERSION}" >> "$KIBANA_DIR/.env"
fi

echo "$CURRENT_COMMIT" > "$COMMIT_FILE"
echo ""
echo "=== Done! Built Kibana at: $OUT_DIR ($CURRENT_COMMIT) ==="
