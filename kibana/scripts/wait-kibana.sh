#!/bin/bash
set -euo pipefail

KIBANA_URL="${KIBANA_URL:-http://localhost:5601}"
KIBANA_USERNAME="${KIBANA_USERNAME:-elastic}"
KIBANA_PASSWORD="${KIBANA_PASSWORD:-${ES_PASSWORD:-changeme}}"
MAX_RETRIES=60
INTERVAL=5

echo "Waiting for Kibana at $KIBANA_URL..."
for i in $(seq 1 $MAX_RETRIES); do
  if curl -sf -u "$KIBANA_USERNAME:$KIBANA_PASSWORD" \
      "$KIBANA_URL/api/status" 2>/dev/null \
      | grep -q '"level":"available"'; then
    echo "Kibana is ready."
    exit 0
  fi
  echo "  attempt $i/$MAX_RETRIES — retrying in ${INTERVAL}s..."
  sleep $INTERVAL
done

echo "ERROR: Kibana did not become available after $((MAX_RETRIES * INTERVAL))s"
exit 1
