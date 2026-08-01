#!/usr/bin/env bash
set -euo pipefail

KIBANA_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$KIBANA_DIR/.env" ]; then
  set -a; source "$KIBANA_DIR/.env"; set +a
fi

LOCAL_DIR="${LOCAL_DIR:-dist}"
OUT_DIR="$KIBANA_DIR/$LOCAL_DIR/kibana/dist"
DIST="$KIBANA_DIR/$LOCAL_DIR"
LOG_DIR="$KIBANA_DIR/logs"
mkdir -p "$LOG_DIR"

run() {
  local log="$LOG_DIR/$1.log"
  echo "=== $1 (log: $log) ==="
  shift
  "$@" >> "$log" 2>&1
}

run clone    "$KIBANA_DIR/scripts/clone.sh"
run bootstrap "$KIBANA_DIR/scripts/bootstrap.sh"
run compile  "$KIBANA_DIR/scripts/compile.sh"

echo "=== Starting Kibana stack ==="
docker compose -f "$KIBANA_DIR/docker-compose.yml" up --build -d "$@"

if [ "${DELETE_DIST:-false}" = "true" ]; then
  echo "=== Deleting dist directory ==="
  rm -rf "$DIST"
fi
