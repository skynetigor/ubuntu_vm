#!/bin/bash
set -euo pipefail

PASSWORD="${KIBANA_BRANCH:-main}"

echo "=== Kibana Dev Container ==="
echo "    Branch  : ${KIBANA_BRANCH:-main}"
echo "    Password: $PASSWORD"

# Process config template — substitutes ${KIBANA_BRANCH} with the actual value
envsubst < /etc/kibana-config/kibana.dev.yml > /opt/kibana/config/kibana.yml

# ES cluster health passes before the native security realm finishes initializing,
# so retry until the _password API accepts the request.
echo "=== Setting kibana_system password ==="
for i in $(seq 1 60); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    -u "elastic:${PASSWORD}" \
    "http://localhost:9200/_security/user/kibana_system/_password" \
    -H 'Content-Type: application/json' \
    -d "{\"password\": \"${PASSWORD}\"}")
  if [ "$STATUS" = "200" ]; then
    echo "kibana_system password set."
    break
  fi
  if [ "$i" -eq 60 ]; then
    echo "ERROR: could not set kibana_system password after 60 attempts (last HTTP $STATUS)"
    exit 1
  fi
  echo "  attempt $i/60: HTTP $STATUS — retrying in 5s..."
  sleep 5
done

echo "=== Starting Kibana ==="
exec /opt/kibana/bin/kibana
