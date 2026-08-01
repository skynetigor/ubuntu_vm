#!/usr/bin/env bash
# Upserts Kibana action connectors from a YAML file.
#
# Required env vars:
#   CONNECTORS_FILE — path to connectors.yml
#
# Optional env vars (read from kibana/.env if present):
#   KIBANA_URL      — default: http://localhost:5601
#   KIBANA_USERNAME — default: elastic
#   KIBANA_PASSWORD — default: changeme
set -euo pipefail

KIBANA_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$KIBANA_DIR/.env" ]; then
  set -a; source "$KIBANA_DIR/.env"; set +a
fi

KIBANA_URL="${KIBANA_URL:-http://localhost:5601}"
KIBANA_USERNAME="${KIBANA_USERNAME:-elastic}"
KIBANA_PASSWORD="${KIBANA_PASSWORD:-changeme}"
: "${CONNECTORS_FILE:?CONNECTORS_FILE is required}"

AUTH="$(printf '%s:%s' "$KIBANA_USERNAME" "$KIBANA_PASSWORD" | base64 -w 0)"

curl_kibana() {
  curl -sf \
    -H "Authorization: Basic $AUTH" \
    -H "kbn-xsrf: true" \
    -H "x-elastic-internal-origin: Kibana" \
    -H "Content-Type: application/json" \
    "$@"
}

echo "=== Fetching existing connectors from $KIBANA_URL ==="
EXISTING_JSON=$(curl_kibana "$KIBANA_URL/api/actions/connectors")

TMPFILE=$(mktemp)
trap 'rm -f "$TMPFILE"' EXIT
printf '%s' "$EXISTING_JSON" > "$TMPFILE"

python3 - "$CONNECTORS_FILE" "$TMPFILE" "$KIBANA_URL" "$AUTH" <<'PYEOF'
import json, subprocess, sys

connectors_path, existing_path, base_url, auth = sys.argv[1:]

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not installed — run: pip3 install pyyaml", file=sys.stderr)
    sys.exit(1)

with open(connectors_path) as f:
    connectors = yaml.safe_load(f)

with open(existing_path) as f:
    existing_by_name = {c['name']: c['id'] for c in json.load(f)}

headers = [
    "-H", f"Authorization: Basic {auth}",
    "-H", "kbn-xsrf: true",
    "-H", "x-elastic-internal-origin: Kibana",
    "-H", "Content-Type: application/json",
]

errors = 0
for connector in connectors:
    name = connector['name']
    try:
        if name in existing_by_name:
            conn_id = existing_by_name[name]
            print(f"=== Replacing: {name} ===")
            subprocess.run(
                ["curl", "-sf", "-X", "DELETE"] + headers +
                [f"{base_url}/api/actions/connector/{conn_id}"],
                check=True,
            )
        else:
            print(f"=== Creating: {name} ===")

        result = subprocess.run(
            ["curl", "-sf", "-X", "POST"] + headers +
            ["-d", json.dumps(connector), f"{base_url}/api/actions/connector"],
            capture_output=True, text=True, check=True,
        )
        r = json.loads(result.stdout)
        print(f"    id: {r.get('id')}")
    except Exception as e:
        print(f"ERROR [{name}]: {e}", file=sys.stderr)
        errors += 1

sys.exit(1 if errors else 0)
PYEOF

echo "=== Done ==="
