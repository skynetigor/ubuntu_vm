#!/bin/bash
set -euo pipefail

export NVM_DIR="/opt/nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

REPO_DIR="/opt/kibana"
PASSWORD="${KIBANA_BRANCH:-main}"

echo "========================================"
echo " Kibana Dev Container"
echo " Branch  : ${KIBANA_BRANCH:-main}"
echo " Password: $PASSWORD"
echo "========================================"

cd "$REPO_DIR"
nvm use

# ── Kibana config ────────────────────────────────────────────────────────────
echo "=== Writing config/kibana.dev.yml ==="
envsubst < /etc/kibana-config/kibana.dev.yml > "$REPO_DIR/config/kibana.dev.yml"
chown kibana:kibana "$REPO_DIR/config/kibana.dev.yml"

# ── Start Elasticsearch (must run as non-root) ───────────────────────────────
echo "=== Starting Elasticsearch (password: $PASSWORD) ==="
su -s /bin/bash kibana -c "
  source /opt/nvm/nvm.sh
  cd /opt/kibana
  nvm use
  yarn es snapshot \
    --license trial \
    -E xpack.ml.enabled=false \
    -E xpack.security.authc.api_key.enabled=true \
    --kibanaUrl http://localhost:5601 \
    --password '$PASSWORD'
" &

ES_PID=$!

cleanup() {
  echo "=== Shutting down ==="
  kill "$ES_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

# ── Wait for Elasticsearch ───────────────────────────────────────────────────
echo "=== Waiting for Elasticsearch ==="
until curl -s -u "elastic:${PASSWORD}" http://localhost:9200/_cluster/health >/dev/null 2>&1; do
  sleep 5
done
echo "=== Elasticsearch is ready ==="

# ── Start Kibana ─────────────────────────────────────────────────────────────
echo "=== Starting Kibana ==="
exec su -s /bin/bash kibana -c "
  source /opt/nvm/nvm.sh
  cd /opt/kibana
  nvm use
  yarn kbn start
"
