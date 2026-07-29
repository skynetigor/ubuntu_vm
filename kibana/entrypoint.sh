#!/bin/bash
set -euo pipefail

PASSWORD="${KIBANA_BRANCH:-main}"

echo "=== Kibana Dev Container ==="
echo "    Branch  : ${KIBANA_BRANCH:-main}"
echo "    Password: $PASSWORD"

# Process config template — substitutes ${KIBANA_BRANCH} with the actual value
envsubst < /etc/kibana-config/kibana.dev.yml > /opt/kibana/config/kibana.yml

# ES is guaranteed healthy by depends_on healthcheck in docker-compose.
# Set the kibana_system password so Kibana can connect.
echo "=== Setting kibana_system password ==="
curl -sf -X POST \
  -u "elastic:${PASSWORD}" \
  "http://localhost:9200/_security/user/kibana_system/_password" \
  -H 'Content-Type: application/json' \
  -d "{\"password\": \"${PASSWORD}\"}"

echo "=== Starting Kibana ==="
exec /opt/kibana/bin/kibana
