#!/bin/bash
set -euo pipefail
: "${JWT_SECRET:?JWT_SECRET must be set}"
bash /app/scripts/register-tunnel.sh || true
exec node /app/src/index.js
