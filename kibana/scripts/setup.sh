#!/bin/bash
set -euo pipefail

SETUP_DIR="$(cd "$(dirname "$0")" && pwd)"
NODE="/opt/kibana/node/default/bin/node"

LOG_DIR="$SETUP_DIR/logs"
mkdir -p "$LOG_DIR"

run() {
  local name="$1" log="$LOG_DIR/$1.log"
  echo "=== $name (log: $log) ==="
  shift
  if ! "$@" >> "$log" 2>&1; then
    echo "=== ERROR: $name failed — see $log ==="
  fi
}

runNode() {
  run "$1" "$NODE" "$SETUP_DIR/$1"
}

run wait-kibana  bash "$SETUP_DIR/wait-kibana.sh"
run register-tunnel  bash "$SETUP_DIR/register-tunnel.sh"
run kibana-init  bash "$SETUP_DIR/kibana-init.sh"
run npm-install  npm --prefix "$SETUP_DIR" install --omit=dev
runNode upload_connectors.js
runNode upload_workflows.js
