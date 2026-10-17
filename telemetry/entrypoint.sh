#!/bin/bash
set -euo pipefail
# Registers <CF_SUBDOMAIN>.<CF_DOMAIN> in the Cloudflare tunnel (skips itself when CF_* is not configured).
bash /app/scripts/register-tunnel.sh || true
exec node /app/src/index.js
