#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
echo $REPO_DIR
KIBANA_DIR="$REPO_DIR/kibana"

chmod 600 "$REPO_DIR/elastic_dev_vm/id_ed25519"

if [ -f "$KIBANA_DIR/.env" ]; then
  set -a; source "$KIBANA_DIR/.env"; set +a
fi

LOCAL_DIR="${LOCAL_DIR:-dist}"
DIST="$KIBANA_DIR/$LOCAL_DIR"

"$KIBANA_DIR/scripts/clone.sh"
"$KIBANA_DIR/scripts/bootstrap.sh"
"$KIBANA_DIR/scripts/compile.sh"

docker compose -f "$REPO_DIR/docker-compose.yml" up --build -d "$@"

if [ "${DELETE_DIST:-false}" = "true" ]; then
  echo "=== Deleting dist directory ==="
  rm -rf "$DIST"
fi
