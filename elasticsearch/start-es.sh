#!/usr/bin/env bash
set -euo pipefail

ES_HOME=/opt/elasticsearch
ES_PASSWORD="${ES_PASSWORD:-changeme}"
ES_LICENSE="${ES_LICENSE:-trial}"
ES_DATA_DIR=/var/lib/elasticsearch/data
ES_LOGS_DIR=/var/lib/elasticsearch/logs

mkdir -p "$ES_DATA_DIR" "$ES_LOGS_DIR" "$ES_HOME/ES_TMPDIR"

# ── Configure elasticsearch.yml ───────────────────────────────────────────────
# Mirrors install_archive.ts lines 81-83 from kbn-es, plus persistent data/log paths
cat >> "$ES_HOME/config/elasticsearch.yml" <<EOF
path.data: ${ES_DATA_DIR}
path.logs: ${ES_LOGS_DIR}
xpack.security.enabled: true
xpack.license.self_generated.type: ${ES_LICENSE}
EOF

# ── Bootstrap keystore ────────────────────────────────────────────────────────
# install_archive.ts lines 84-87: bootstrap keystore password
# -xf: read from stdin (-x), force overwrite if key exists (-f)
"$ES_HOME/bin/elasticsearch-keystore" create
printf '%s' "$ES_PASSWORD" | "$ES_HOME/bin/elasticsearch-keystore" add -xf bootstrap.password

# ── Start Elasticsearch ───────────────────────────────────────────────────────
echo "=== Starting Elasticsearch ==="

export JAVA_HOME=""
export ES_TMPDIR="$ES_HOME/ES_TMPDIR"
# cluster.ts lines 607-614: default heap if Xmx not already set
export ES_JAVA_OPTS="${ES_JAVA_OPTS:--Xms1536m -Xmx1536m}"

# cluster.ts lines 395-399: default -E flags always applied
# enrollment.enabled=false prevents ES 8+/9+ auto-configuration from overriding bootstrap.password
"$ES_HOME/bin/elasticsearch" \
  -E action.destructive_requires_name=true \
  -E cluster.routing.allocation.disk.threshold_enabled=false \
  -E ingest.geoip.downloader.enabled=false \
  -E network.host=0.0.0.0 \
  -E search.check_ccs_compatibility=true \
  -E xpack.ml.enabled=false \
  -E xpack.security.authc.api_key.enabled=true \
  -E xpack.security.enrollment.enabled=false \
  -E xpack.security.http.ssl.enabled=false \
  &

ES_PID=$!
trap "echo '=== Stopping Elasticsearch ==='; kill $ES_PID 2>/dev/null || true" EXIT INT TERM

# ── Wait for cluster to be yellow or green ────────────────────────────────────
# First wait for ES to accept connections (ignoring auth), then verify credentials work.
echo "=== Waiting for Elasticsearch ==="
until curl -s "http://localhost:9200/_cluster/health" -o /dev/null 2>/dev/null; do
  sleep 3
done
echo "=== Elasticsearch is responding, waiting for auth ==="
until curl -sf -u "elastic:${ES_PASSWORD}" "http://localhost:9200/_cluster/health" >/dev/null 2>&1; do
  sleep 3
done
echo "=== Elasticsearch is ready ==="

# ── Wait for security API (cluster health passes before native realm is ready) ─
echo "=== Waiting for security API ==="
for i in $(seq 1 60); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
    -u "elastic:${ES_PASSWORD}" \
    "http://localhost:9200/_security/user/elastic")
  [ "$STATUS" = "200" ] && break
  [ "$i" -eq 60 ] && { echo "ERROR: security API not ready after 60 attempts"; kill $ES_PID; exit 1; }
  echo "  attempt $i/60: HTTP $STATUS — retrying in 3s..."
  sleep 3
done
echo "=== Security API ready ==="

# ── Set passwords for all reserved users ─────────────────────────────────────
# native_realm.ts lines 79-86: iterate reserved users, set password
echo "=== Configuring users ==="
for USER in elastic kibana_system logstash_system beats_system apm_system remote_monitoring_user; do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
    -u "elastic:${ES_PASSWORD}" \
    "http://localhost:9200/_security/user/${USER}/_password" \
    -H 'Content-Type: application/json' \
    -d "{\"password\":\"${ES_PASSWORD}\"}")
  [ "$STATUS" = "200" ] && echo "  password set: $USER" || echo "  skipped: $USER (HTTP $STATUS)"
done

# native_realm.ts lines 138-171: system_indices_superuser role + user
curl -sf -X PUT \
  -u "elastic:${ES_PASSWORD}" \
  "http://localhost:9200/_security/role/system_indices_superuser" \
  -H 'Content-Type: application/json' \
  -d '{
    "cluster": ["all"],
    "indices": [{"names":["*"],"privileges":["all"],"allow_restricted_indices":true}],
    "applications": [{"application":"*","privileges":["*"],"resources":["*"]}],
    "run_as": ["*"]
  }' >/dev/null || true

curl -sf -X PUT \
  -u "elastic:${ES_PASSWORD}" \
  "http://localhost:9200/_security/user/system_indices_superuser" \
  -H 'Content-Type: application/json' \
  -d "{\"password\":\"${ES_PASSWORD}\",\"roles\":[\"system_indices_superuser\"]}" >/dev/null || true

echo "=== Setup complete ==="

wait $ES_PID
