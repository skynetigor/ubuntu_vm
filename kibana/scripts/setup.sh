#!/bin/bash
set -euo pipefail

SETUP_DIR="$(cd "$(dirname "$0")" && pwd)"
NODE="/opt/kibana/node/default/bin/node"

LOG_DIR="$SETUP_DIR/logs"
mkdir -p "$LOG_DIR"

run() {
  local log="$LOG_DIR/$1.log"
  echo "=== $1 (log: $log) ==="
  shift
  "$@" >> "$log" 2>&1
}

runNode() {
  run "$1" "$NODE" "$SETUP_DIR/$1"
}

run wait-kibana  bash "$SETUP_DIR/wait-kibana.sh"
run kibana-init  bash "$SETUP_DIR/kibana-init.sh"
runNode upload_connectors.js
runNode upload_workflows.js
