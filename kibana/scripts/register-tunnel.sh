#!/usr/bin/env bash
# Registers (or updates) a public hostname in a Cloudflare tunnel via the API.
#
# Required env vars (set in kibana/.env or export before running):
#   CF_API_TOKEN   — API token with Cloudflare Tunnel:Edit permission
#   CF_ACCOUNT_ID  — Account ID (Cloudflare dashboard → right sidebar)
#   CF_TUNNEL_ID   — Tunnel ID (Zero Trust → Networks → Tunnels → tunnel name)
#   CF_DOMAIN      — Base domain, e.g. skynetapp.dev
#   CF_SUBDOMAIN      — Subdomain prefix, e.g. wf
#   CF_SERVICE_URL — Backend service URL, e.g. http://kibana:5601
set -euo pipefail

KIBANA_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$KIBANA_DIR/.env" ]; then
  set -a; source "$KIBANA_DIR/.env"; set +a
fi

if [ -z "${CF_API_TOKEN:-}" ] || [ -z "${CF_ACCOUNT_ID:-}" ] || \
   [ -z "${CF_TUNNEL_ID:-}" ] || [ -z "${CF_DOMAIN:-}" ] || \
   [ -z "${CF_SUBDOMAIN:-}" ] || [ -z "${CF_SERVICE_URL:-}" ]; then
  echo "=== No Cloudflare configuration (CF_*). Skipping. === "
  exit 0
fi

export CF_HOSTNAME="${CF_SUBDOMAIN}.${CF_DOMAIN}"

API="https://api.cloudflare.com/client/v4"
AUTH=(-H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json")

echo "=== CF vars ==="
echo "  CF_API_TOKEN:   ${CF_API_TOKEN:+set (${#CF_API_TOKEN} chars)}"
echo "  CF_ACCOUNT_ID:  ${CF_ACCOUNT_ID:-unset}"
echo "  CF_TUNNEL_ID:   ${CF_TUNNEL_ID:-unset}"
echo "  CF_DOMAIN:      ${CF_DOMAIN:-unset}"
echo "  CF_SUBDOMAIN:   ${CF_SUBDOMAIN:-unset}"
echo "  CF_SERVICE_URL: ${CF_SERVICE_URL:-unset}"

echo "=== Fetching current tunnel config ==="
set +e
CURRENT=$(curl -s "${AUTH[@]}" \
  "$API/accounts/$CF_ACCOUNT_ID/cfdtunnel/$CF_TUNNEL_ID/configurations")
CURL_EXIT=$?
set -e
echo "curl exit: $CURL_EXIT"
echo "$CURRENT"
if [ "$CURL_EXIT" -ne 0 ]; then
  echo "ERROR: curl failed with exit code $CURL_EXIT"
  exit 1
fi
if ! echo "$CURRENT" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('success') else 1)" 2>/dev/null; then
  echo "ERROR: Cloudflare API returned failure"
  exit 1
fi

echo "=== Updating ingress: $CF_HOSTNAME → $CF_SERVICE_URL ==="
NEW_CONFIG=$(echo "$CURRENT" | python3 -c "
import json, sys, os
data = json.load(sys.stdin)
config = data.get('result', {}).get('config', {})
ingress = config.get('ingress', [])
hostname = os.environ['CF_HOSTNAME']
service  = os.environ['CF_SERVICE_URL']
# Drop existing rule for this hostname and the catch-all (re-added below)
ingress = [r for r in ingress if r.get('hostname') and r['hostname'] != hostname]
# Prepend new rule; catch-all must always be last
ingress = [{'hostname': hostname, 'service': service}] + ingress + [{'service': 'http_status:404'}]
config['ingress'] = ingress
print(json.dumps({'config': config}))
")

RESULT=$(curl -s -X PUT "${AUTH[@]}" \
  -d "$NEW_CONFIG" \
  "$API/accounts/$CF_ACCOUNT_ID/cfdtunnel/$CF_TUNNEL_ID/configurations")
echo "=== Cloudflare tunnel registration result ==="
echo "$RESULT"

python3 -c "
import json, sys
r = json.load(sys.stdin)
if r.get('success'):
    print('=== Registered successfully ===')
else:
    print('ERROR:', r.get('errors'))
    sys.exit(1)
" <<< "$RESULT"
