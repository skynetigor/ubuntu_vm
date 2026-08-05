#!/usr/bin/env bash
set -euo pipefail

KIBANA_DIR="$(cd "$(dirname "$0")/.." && pwd)"

if [ -f "$KIBANA_DIR/.env" ]; then
  set -a; source "$KIBANA_DIR/.env"; set +a
fi

KIBANA_FORK="${KIBANA_FORK:-https://github.com/elastic/kibana}"
KIBANA_BRANCH="${KIBANA_BRANCH:-}"
KIBANA_COMMIT="${KIBANA_COMMIT:-}"
KIBANA_SRC="${KIBANA_SRC:-$KIBANA_DIR/src}"
COMMIT_FILE="$KIBANA_SRC/.clonecommit"

# At least one of KIBANA_BRANCH or KIBANA_COMMIT must be set
if [ -z "$KIBANA_BRANCH" ] && [ -z "$KIBANA_COMMIT" ]; then
  # Fallback to main so the script stays usable without a .env
  KIBANA_BRANCH="main"
fi

# Remove partial/broken clone so we fall through to a fresh clone below
if [ -d "$KIBANA_SRC" ] && ! git -C "$KIBANA_SRC" rev-parse HEAD >/dev/null 2>&1; then
  echo "=== Detected broken/partial clone — removing and re-cloning ==="
  rm -rf "$KIBANA_SRC"
  rm -f "$COMMIT_FILE"
fi

if [ -d "$KIBANA_SRC" ]; then
  git -C "$KIBANA_SRC" remote set-url origin "$KIBANA_FORK"

  if [ -n "$KIBANA_BRANCH" ]; then
    echo "=== Fetching $KIBANA_BRANCH from $KIBANA_FORK ==="
    git -C "$KIBANA_SRC" fetch --depth 1 origin "$KIBANA_BRANCH"
  else
    echo "=== Fetching commit $KIBANA_COMMIT from $KIBANA_FORK ==="
    git -C "$KIBANA_SRC" fetch --depth 1 origin "$KIBANA_COMMIT"
  fi

  REMOTE_COMMIT=$(git -C "$KIBANA_SRC" rev-parse FETCH_HEAD)
  STORED_COMMIT=$(cat "$COMMIT_FILE" 2>/dev/null || echo "")
  if [ "$REMOTE_COMMIT" = "$STORED_COMMIT" ]; then
    echo "=== Skipping — already at $REMOTE_COMMIT ==="
    exit 0
  fi
  echo "=== Updating to $REMOTE_COMMIT ==="
  git -C "$KIBANA_SRC" reset --hard FETCH_HEAD
else
  mkdir -p "$(dirname "$KIBANA_SRC")"

  if [ -n "$KIBANA_BRANCH" ]; then
    echo "=== Cloning $KIBANA_FORK ($KIBANA_BRANCH) ==="
    git clone --depth 1 --branch "$KIBANA_BRANCH" "$KIBANA_FORK" "$KIBANA_SRC"
  else
    echo "=== Fetching commit $KIBANA_COMMIT from $KIBANA_FORK ==="
    git init "$KIBANA_SRC"
    git -C "$KIBANA_SRC" remote add origin "$KIBANA_FORK"
    git -C "$KIBANA_SRC" fetch --depth 1 origin "$KIBANA_COMMIT"
    git -C "$KIBANA_SRC" checkout FETCH_HEAD
  fi
fi

COMMIT=$(git -C "$KIBANA_SRC" rev-parse HEAD)
echo "$COMMIT" > "$COMMIT_FILE"
echo "=== Done at $COMMIT ==="
