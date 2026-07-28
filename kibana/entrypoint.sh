#!/bin/bash
set -euo pipefail

export NVM_DIR="/root/.nvm"
# shellcheck source=/dev/null
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

REPO_DIR="/opt/kibana"
FORK_URL="${KIBANA_REPO_URL:-https://github.com/elastic/kibana}"
BRANCH="${KIBANA_BRANCH:-main}"
PASSWORD="$BRANCH"

echo "========================================"
echo " Kibana Dev Container"
echo " Repo   : $FORK_URL"
echo " Branch : $BRANCH"
echo " Password: $PASSWORD"
echo "========================================"

# ── Clone or update ──────────────────────────────────────────────────────────
if [ -d "$REPO_DIR/.git" ] && git -C "$REPO_DIR" rev-parse HEAD >/dev/null 2>&1; then
  echo "=== Updating existing clone ==="
  git -C "$REPO_DIR" remote set-url origin "$FORK_URL"
  git -C "$REPO_DIR" fetch origin --prune
  git -C "$REPO_DIR" checkout "$BRANCH" 2>/dev/null \
    || git -C "$REPO_DIR" checkout -b "$BRANCH" "origin/$BRANCH"
  git -C "$REPO_DIR" reset --hard "origin/$BRANCH"
else
  echo "=== Cloning $FORK_URL (branch: $BRANCH) ==="
  rm -rf "$REPO_DIR"
  git clone --depth 1 --branch "$BRANCH" "$FORK_URL" "$REPO_DIR"
fi

cd "$REPO_DIR"
echo "HEAD: $(git log -1 --format='%H %s')"

# ── Node.js ──────────────────────────────────────────────────────────────────
echo "=== Installing Node.js from .nvmrc ==="
nvm install
nvm use

# ── Bootstrap ────────────────────────────────────────────────────────────────
echo "=== Bootstrapping ==="
if ! command -v yarn >/dev/null 2>&1; then
  npm install -g yarn
fi
# KBN_BOOTSTRAP_NO_PREBUILT skips webpack bundle builds (monaco, ui-shared-deps)
# which are not needed for running Kibana in dev mode.
KBN_BOOTSTRAP_NO_PREBUILT=true yarn kbn bootstrap

# ── Kibana config ────────────────────────────────────────────────────────────
echo "=== Writing config/kibana.dev.yml ==="
envsubst < /etc/kibana-config/kibana.dev.yml > "$REPO_DIR/config/kibana.dev.yml"

# ── Start Elasticsearch ──────────────────────────────────────────────────────
echo "=== Starting Elasticsearch (password: $PASSWORD) ==="
yarn es snapshot \
  --license trial \
  -E xpack.ml.enabled=false \
  -E xpack.security.authc.api_key.enabled=true \
  --kibanaUrl http://localhost:5601 \
  --password "$PASSWORD" \
  &

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
yarn kbn start
