#!/usr/bin/env bash
set -euo pipefail

KIBANA_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$KIBANA_DIR/.env" ]; then
  set -a; source "$KIBANA_DIR/.env"; set +a
fi

LOCAL_DIR="${LOCAL_DIR:-dist}"
OUT_DIR="$KIBANA_DIR/$LOCAL_DIR/kibana/dist"
DIST="$KIBANA_DIR/$LOCAL_DIR"
if [ ! -d "$OUT_DIR" ]; then
  echo "=== Kibana dist not found — building ==="
  "$KIBANA_DIR/scripts/clone.sh"
  "$KIBANA_DIR/scripts/bootstrap.sh"
  "$KIBANA_DIR/scripts/compile.sh"
fi

echo "=== Starting Kibana stack ==="
docker compose -f "$KIBANA_DIR/docker-compose.yml" up --build -d "$@"

if [ "${DIST:-false}" = "true" ]; then
  echo "=== Deleting dist directory ==="
  rm -rf "$DIST"
fi
