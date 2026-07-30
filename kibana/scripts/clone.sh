#!/usr/bin/env bash
set -euo pipefail

KIBANA_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ -f "$KIBANA_DIR/.env" ]; then
  set -a; source "$KIBANA_DIR/.env"; set +a
fi

KIBANA_FORK="${KIBANA_FORK:-https://github.com/elastic/kibana}"
KIBANA_BRANCH="${KIBANA_BRANCH:-main}"
LOCAL_DIR="${LOCAL_DIR:-dist}"
CLONE_BASE="$KIBANA_DIR/$LOCAL_DIR/kibana"
SRC_DIR="$CLONE_BASE/src"
COMMIT_FILE="$CLONE_BASE/.clonecommit"

if [ -d "$SRC_DIR" ]; then
  git -C "$SRC_DIR" remote set-url origin "$KIBANA_FORK"
  echo "=== Fetching $KIBANA_BRANCH from $KIBANA_FORK ==="
  git -C "$SRC_DIR" fetch --depth 1 origin "$KIBANA_BRANCH"
  REMOTE_COMMIT=$(git -C "$SRC_DIR" rev-parse "origin/$KIBANA_BRANCH")
  STORED_COMMIT=$(cat "$COMMIT_FILE" 2>/dev/null || echo "")
  if [ "$REMOTE_COMMIT" = "$STORED_COMMIT" ]; then
    echo "=== Skipping clone — already at $REMOTE_COMMIT ==="
    exit 0
  fi
  echo "=== Pulling $KIBANA_BRANCH ($REMOTE_COMMIT) ==="
  git -C "$SRC_DIR" reset --hard "origin/$KIBANA_BRANCH"
else
  echo "=== Cloning $KIBANA_FORK ($KIBANA_BRANCH) ==="
  mkdir -p "$CLONE_BASE"
  git clone --depth 1 --branch "$KIBANA_BRANCH" "$KIBANA_FORK" "$SRC_DIR"
fi

COMMIT=$(git -C "$SRC_DIR" rev-parse HEAD)
echo "$COMMIT" > "$COMMIT_FILE"
echo "=== Done at $COMMIT ==="
