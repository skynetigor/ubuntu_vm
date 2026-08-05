#!/usr/bin/env bash
set -euo pipefail

KIBANA_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ -f "$KIBANA_DIR/.env" ]; then
  set -a; source "$KIBANA_DIR/.env"; set +a
fi

export KIBANA_SRC="${KIBANA_SRC:-$KIBANA_DIR/src}"

echo "=== Kibana Local Build ==="
echo "  Fork  : ${KIBANA_FORK:-https://github.com/elastic/kibana}"
echo "  Branch: ${KIBANA_BRANCH:-main}"
echo "  Output: $KIBANA_SRC/dist"
echo ""

"$KIBANA_DIR/scripts/clone.sh"
"$KIBANA_DIR/scripts/bootstrap.sh"
"$KIBANA_DIR/scripts/compile.sh"
