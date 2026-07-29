#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$SCRIPT_DIR/.env" ]; then
  set -a
  source "$SCRIPT_DIR/.env"
  set +a
fi

LOCAL_DIR="${LOCAL_DIR:-dist}"
OUT_DIR="$SCRIPT_DIR/$LOCAL_DIR/kibana/dist"

if [ ! -d "$OUT_DIR" ]; then
  echo "=== Kibana dist not found — running build first ==="
  "$SCRIPT_DIR/build.sh"
fi

echo "=== Starting Kibana stack ==="
docker compose -f "$SCRIPT_DIR/docker-compose.yml" up --build -d "$@"
