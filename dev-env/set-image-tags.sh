#!/bin/bash
# Writes KIBANA_IMAGE_TAG to dev-env/.env based on current commits
# of ubuntu_vm and the Kibana source inside kibana/dist.
#
# Usage: source ./set-image-tags.sh
#        or: bash set-image-tags.sh && docker compose up -d

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

UBUNTU_VM_SHA=$(git -C "$REPO_ROOT" rev-parse --short HEAD)

# Kibana source commit is embedded in kibana/dist (resolve.sh writes it during build).
# Fall back to the ubuntu_vm SHA if not available.
KIBANA_SHA_FILE="$REPO_ROOT/kibana/dist/.kibana_commit"
if [ -f "$KIBANA_SHA_FILE" ]; then
  KIBANA_SHA=$(cat "$KIBANA_SHA_FILE" | cut -c1-7)
else
  KIBANA_SHA="unknown"
fi

KIBANA_IMAGE_TAG="${UBUNTU_VM_SHA}-${KIBANA_SHA}"

ENV_FILE="$SCRIPT_DIR/.env"
if grep -q "^KIBANA_IMAGE_TAG=" "$ENV_FILE" 2>/dev/null; then
  sed -i.bak "s/^KIBANA_IMAGE_TAG=.*/KIBANA_IMAGE_TAG=${KIBANA_IMAGE_TAG}/" "$ENV_FILE"
  rm -f "$ENV_FILE.bak"
else
  echo "KIBANA_IMAGE_TAG=${KIBANA_IMAGE_TAG}" >> "$ENV_FILE"
fi

echo "KIBANA_IMAGE_TAG=${KIBANA_IMAGE_TAG}"
