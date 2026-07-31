#!/bin/bash
set -euo pipefail

ES_PASS="${ES_PASSWORD:-changeme}"
ES_URL="http://elasticsearch:9200"

echo "=== Kibana Dev Container ==="
echo "    Branch  : ${KIBANA_BRANCH:-main}"

if [ -n "${KIBANA_SSH_PRIVATE_KEY_BASE64:-}" ]; then
  echo "$KIBANA_SSH_PRIVATE_KEY_BASE64" | base64 -d > /opt/kibana/config/dev-vm-key
  chmod 600 /opt/kibana/config/dev-vm-key
  echo "    SSH key : /opt/kibana/config/dev-vm-key"
fi

# Process config template — substitutes ${KIBANA_BRANCH} and ${ES_PASSWORD}
envsubst < /etc/kibana-config/kibana.dev.yml > /opt/kibana/config/kibana.yml

# ES cluster health passes before the native security realm finishes initializing,
# so retry until the _password API accepts the request.
echo "=== Setting kibana_system password ==="
for i in $(seq 1 60); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    -u "elastic:${ES_PASS}" \
    "${ES_URL}/_security/user/kibana_system/_password" \
    -H 'Content-Type: application/json' \
    -d "{\"password\": \"${ES_PASS}\"}" 2>/dev/null) || STATUS="000"
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
