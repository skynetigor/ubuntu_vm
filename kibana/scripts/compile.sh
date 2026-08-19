#!/usr/bin/env bash
set -euo pipefail

KIBANA_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ -f "$KIBANA_DIR/.env" ]; then
  set -a; source "$KIBANA_DIR/.env"; set +a
fi

KIBANA_SRC="${KIBANA_SRC:-$KIBANA_DIR/src}"
COMMIT_FILE="$KIBANA_SRC/.compilecommit"

if [ ! -d "$KIBANA_SRC" ]; then
  echo "ERROR: source directory not found: $KIBANA_SRC — run clone.sh and bootstrap.sh first"
  exit 1
fi

CURRENT_COMMIT=$(git -C "$KIBANA_SRC" rev-parse HEAD)
STORED_COMMIT=$(cat "$COMMIT_FILE" 2>/dev/null || echo "")
if [ "$CURRENT_COMMIT" = "$STORED_COMMIT" ]; then
  echo "=== Skipping compile — already at $CURRENT_COMMIT ==="
  exit 0
fi

cd "$KIBANA_SRC"

# ── Node version ──────────────────────────────────────────────────────────────
# set +u: nvm.sh uses unbound variables internally
# shellcheck disable=SC1091
set +u; source "${NVM_DIR:-/home/kibana/.nvm}/nvm.sh"; set -u
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

# ── Move dist to $KIBANA_SRC/dist/ ───────────────────────────────────────────
BUILD_DIR=$(ls -d build/default/kibana-*/ 2>/dev/null | head -1)
if [ -z "$BUILD_DIR" ]; then
  echo "ERROR: build output not found under build/default/ — the build may have failed"
  exit 1
fi
OUT_DIR="$KIBANA_SRC/dist"
rm -rf "$OUT_DIR"
mv "$BUILD_DIR" "$OUT_DIR"

# ── Make .nvmrc available in the Docker build context ────────────────────────
cp .nvmrc "$KIBANA_DIR/.nvmrc"

echo "$CURRENT_COMMIT" > "$COMMIT_FILE"
echo ""
echo "=== Done! Built Kibana at: $OUT_DIR ($CURRENT_COMMIT) ==="
