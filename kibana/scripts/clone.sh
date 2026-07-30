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
  if [ "${PULL:-false}" = "true" ]; then
    echo "=== Pulling latest $KIBANA_BRANCH ==="
    # Update remote URL in case KIBANA_FORK changed in .env
    git -C "$SRC_DIR" remote set-url origin "$KIBANA_FORK"
    git -C "$SRC_DIR" fetch --depth 1 origin "$KIBANA_BRANCH"
    git -C "$SRC_DIR" reset --hard "origin/$KIBANA_BRANCH"
  else
    echo "=== Skipping clone — $SRC_DIR already exists (set PULL=true to pull latest) ==="
  fi
else
  echo "=== Cloning $KIBANA_FORK ($KIBANA_BRANCH) ==="
  git clone --depth 1 --branch "$KIBANA_BRANCH" "$KIBANA_FORK" "$SRC_DIR"
fi
