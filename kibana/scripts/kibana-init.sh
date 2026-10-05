#!/bin/bash
set -euo pipefail

# Kibana post-start initialization. Runs after wait-kibana.sh confirms
# Kibana is accepting requests. Add user creation, space setup, etc. here.

KIBANA_URL="${KIBANA_URL:-http://localhost:5601}"
KIBANA_USERNAME="${KIBANA_USERNAME:-elastic}"
KIBANA_PASSWORD="${KIBANA_PASSWORD:-${ES_PASSWORD:-changeme}}"

ES_HOST="${ES_HOST:-http://elasticsearch:9200}"
response=$(mktemp)
trap 'rm -f "$response"' EXIT

echo '=== Ensuring key-value index exists ==='
status=$(curl --silent --show-error --connect-timeout 10 --max-time 60 \
	--user "elastic:${ES_PASSWORD:-changeme}" \
	--request PUT "${ES_HOST%/}/key-value" \
	--header 'Content-Type: application/json' \
	--data '{"mappings":{"enabled":false}}' \
	--output "$response" --write-out '%{http_code}')

if [[ "$status" == 200 ]]; then
	echo '=== Created key-value index ==='
elif [[ "$status" == 400 ]] && python3 - "$response" <<'PY'
import json
import sys

with open(sys.argv[1], encoding='utf-8') as response:
		error = json.load(response).get('error', {})
sys.exit(0 if isinstance(error, dict) and error.get('type') == 'resource_already_exists_exception' else 1)
PY
then
	echo '=== key-value index already exists; continuing ==='
else
	echo "ERROR: Unable to create key-value index (HTTP $status)" >&2
	exit 1
fi
