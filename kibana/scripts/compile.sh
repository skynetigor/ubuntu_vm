#!/usr/bin/env bash
set -euo pipefail

KIBANA_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ -f "$KIBANA_DIR/.env" ]; then
  set -a; source "$KIBANA_DIR/.env"; set +a
fi

LOCAL_DIR="${LOCAL_DIR:-dist}"
SRC_DIR="$KIBANA_DIR/$LOCAL_DIR/kibana/src"
OUT_DIR="$KIBANA_DIR/$LOCAL_DIR/kibana/dist"

cd "$SRC_DIR"

NODE_VERSION=$(cat .nvmrc)

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

# ── Persist node version into .env so docker-compose can pass it as a build arg ─
# sed -i '' is BSD (macOS); GNU sed (Linux) uses sed -i — use a tmp file for portability
if grep -q "^NODE_VERSION=" "$KIBANA_DIR/.env" 2>/dev/null; then
  tmp=$(mktemp)
  sed "s/^NODE_VERSION=.*/NODE_VERSION=${NODE_VERSION}/" "$KIBANA_DIR/.env" > "$tmp"
  mv "$tmp" "$KIBANA_DIR/.env"
else
  echo "NODE_VERSION=${NODE_VERSION}" >> "$KIBANA_DIR/.env"
fi

# ── Clean up source ───────────────────────────────────────────────────────────
echo "=== Cleaning up source ==="
cd "$KIBANA_DIR"
rm -rf "$SRC_DIR"

echo ""
echo "=== Done! Built Kibana at: $OUT_DIR ==="
