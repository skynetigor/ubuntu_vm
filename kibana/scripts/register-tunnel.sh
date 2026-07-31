#!/usr/bin/env bash
# Registers (or updates) a public hostname in a Cloudflare tunnel via the API.
#
# Required env vars (set in kibana/.env or export before running):
#   CF_API_TOKEN   — API token with Cloudflare Tunnel:Edit permission
#   CF_ACCOUNT_ID  — Account ID (Cloudflare dashboard → right sidebar)
#   CF_TUNNEL_ID   — Tunnel ID (Zero Trust → Networks → Tunnels → tunnel name)
#   DNS            — Base domain, e.g. skynetapp.dev
#   SUBDOMAIN      — Subdomain prefix, e.g. wf
#   CF_SERVICE_URL — Backend service URL, e.g. http://kibana:5601
set -euo pipefail

KIBANA_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$KIBANA_DIR/.env" ]; then
  set -a; source "$KIBANA_DIR/.env"; set +a
fi

: "${CF_API_TOKEN:?CF_API_TOKEN is required}"
: "${CF_ACCOUNT_ID:?CF_ACCOUNT_ID is required}"
: "${CF_TUNNEL_ID:?CF_TUNNEL_ID is required}"
: "${DNS:?DNS is required}"
: "${SUBDOMAIN:?SUBDOMAIN is required}"
: "${CF_SERVICE_URL:?CF_SERVICE_URL is required}"

export CF_HOSTNAME="${SUBDOMAIN}.${DNS}"

API="https://api.cloudflare.com/client/v4"
AUTH=(-H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json")

echo "=== Fetching current tunnel config ==="
CURRENT=$(curl -sf "${AUTH[@]}" \
  "$API/accounts/$CF_ACCOUNT_ID/cfdtunnel/$CF_TUNNEL_ID/configurations")

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

RESULT=$(curl -sf -X PUT "${AUTH[@]}" \
  -d "$NEW_CONFIG" \
  "$API/accounts/$CF_ACCOUNT_ID/cfdtunnel/$CF_TUNNEL_ID/configurations")

python3 -c "
import json, sys
r = json.load(sys.stdin)
if r.get('success'):
    print('=== Registered successfully ===')
else:
    print('ERROR:', r.get('errors'))
    sys.exit(1)
" <<< "$RESULT"
