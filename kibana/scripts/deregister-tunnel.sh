#!/usr/bin/env bash
# Removes a Cloudflare tunnel ingress rule and DNS CNAME for CF_SUBDOMAIN.
#
# Required env vars (same as register-tunnel.sh, minus CF_SERVICE_URL):
#   CF_API_TOKEN   — API token with Cloudflare Tunnel:Edit permission
#   CF_ACCOUNT_ID  — Account ID
#   CF_ZONE_ID     — Zone ID for the domain
#   CF_TUNNEL_ID   — Tunnel ID
#   CF_DOMAIN      — Base domain, e.g. skynetapp.dev
#   CF_SUBDOMAIN   — Subdomain prefix to remove, e.g. my-preview
set -euo pipefail

KIBANA_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ -f "$KIBANA_DIR/.env" ]; then
  set -a; source "$KIBANA_DIR/.env"; set +a
fi

if [ -z "${CF_API_TOKEN:-}" ] || [ -z "${CF_ACCOUNT_ID:-}" ] || \
   [ -z "${CF_ZONE_ID:-}" ]   || [ -z "${CF_TUNNEL_ID:-}" ] || \
   [ -z "${CF_DOMAIN:-}" ]    || [ -z "${CF_SUBDOMAIN:-}" ]; then
  echo "=== No Cloudflare configuration (CF_*). Skipping. ==="
  exit 0
fi

export CF_HOSTNAME="${CF_SUBDOMAIN}.${CF_DOMAIN}"
API="https://api.cloudflare.com/client/v4"
AUTH=(-H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json")

echo "=== CF vars ==="
echo "  CF_ACCOUNT_ID: ${CF_ACCOUNT_ID:-unset}"
echo "  CF_ZONE_ID:    ${CF_ZONE_ID:-unset}"
echo "  CF_TUNNEL_ID:  ${CF_TUNNEL_ID:-unset}"
echo "  CF_HOSTNAME:   ${CF_HOSTNAME}"

# ── 1. Fetch current tunnel ingress config ────────────────────────────────────
echo "=== Fetching current tunnel config ==="
set +e
CURRENT=$(curl -s "${AUTH[@]}" \
  "$API/accounts/$CF_ACCOUNT_ID/cfd_tunnel/$CF_TUNNEL_ID/configurations")
CURL_EXIT=$?
set -e
if [ "$CURL_EXIT" -ne 0 ]; then
  echo "ERROR: curl failed with exit code $CURL_EXIT"
  exit 1
fi
if ! echo "$CURRENT" | python3 -c \
     "import json,sys; d=json.load(sys.stdin); sys.exit(0 if d.get('success') else 1)" 2>/dev/null; then
  echo "ERROR: Cloudflare API returned failure"
  echo "$CURRENT"
  exit 1
fi

# ── 2. Remove the ingress rule for this hostname ──────────────────────────────
echo "=== Removing ingress rule for $CF_HOSTNAME ==="
NEW_CONFIG=$(echo "$CURRENT" | python3 -c "
import json, sys, os
data = json.load(sys.stdin)
config = data.get('result', {}).get('config', {})
ingress = config.get('ingress', [])
hostname = os.environ['CF_HOSTNAME']
# Keep all rules except the one for this hostname; catch-all (no hostname) stays
ingress = [r for r in ingress if r.get('hostname') != hostname]
# Ensure catch-all is present
if not any(not r.get('hostname') for r in ingress):
    ingress.append({'service': 'http_status:404'})
config['ingress'] = ingress
print(json.dumps({'config': config}))
")

RESULT=$(curl -s -X PUT "${AUTH[@]}" \
  -d "$NEW_CONFIG" \
  "$API/accounts/$CF_ACCOUNT_ID/cfd_tunnel/$CF_TUNNEL_ID/configurations")

python3 -c "
import json, sys
r = json.load(sys.stdin)
if r.get('success'):
    print('=== Ingress rule removed ===')
else:
    print('ERROR:', r.get('errors'))
    sys.exit(1)
" <<< "$RESULT"

# ── 3. Delete the DNS CNAME record ───────────────────────────────────────────
echo "=== Looking up DNS CNAME for $CF_HOSTNAME ==="
EXISTING=$(curl -s "${AUTH[@]}" \
  "$API/zones/$CF_ZONE_ID/dns_records?type=CNAME&name=$CF_HOSTNAME")
RECORD_ID=$(echo "$EXISTING" | python3 -c "
import json, sys
records = json.load(sys.stdin).get('result', [])
print(records[0]['id'] if records else '')
")

if [ -n "$RECORD_ID" ]; then
  DNS_RESULT=$(curl -s -X DELETE "${AUTH[@]}" \
    "$API/zones/$CF_ZONE_ID/dns_records/$RECORD_ID")
  python3 -c "
import json, sys
r = json.load(sys.stdin)
if r.get('success'):
    print('=== DNS record deleted ===')
else:
    print('ERROR:', r.get('errors'))
    sys.exit(1)
" <<< "$DNS_RESULT"
else
  echo "=== No DNS CNAME found for $CF_HOSTNAME — skipping DNS deletion ==="
fi
