#!/bin/bash
set -euo pipefail

SETUP_DIR="$(cd "$(dirname "$0")" && pwd)"
NODE="/opt/kibana/node/default/bin/node"

exec "$NODE" "$SETUP_DIR/setup.js"
