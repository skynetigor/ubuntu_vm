#!/usr/bin/env bash
set -euo pipefail

KIBANA_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ -f "$KIBANA_DIR/.env" ]; then
  set -a; source "$KIBANA_DIR/.env"; set +a
fi

KIBANA_FORK="${KIBANA_FORK:-https://github.com/elastic/kibana}"
KIBANA_BRANCH="${KIBANA_BRANCH:-main}"
LOCAL_DIR="${LOCAL_DIR:-dist}"
SRC_DIR="$KIBANA_DIR/$LOCAL_DIR/kibana/src"

if [ -d "$SRC_DIR" ]; then
  echo "=== Skipping clone — $SRC_DIR already exists ==="
else
  echo "=== Cloning $KIBANA_FORK ($KIBANA_BRANCH) ==="
  git clone --depth 1 --branch "$KIBANA_BRANCH" "$KIBANA_FORK" "$SRC_DIR"
fi
