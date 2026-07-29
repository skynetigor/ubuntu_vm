#!/usr/bin/env bash
# Replicates `yarn es snapshot` without requiring the Kibana repo.
# Sources:
#   src/platform/packages/shared/kbn-es/src/artifact.ts      (manifest URL, platform mapping)
#   src/platform/packages/shared/kbn-es/src/cluster.ts        (startup flags, heap)
#   src/platform/packages/shared/kbn-es/src/install/          (extraction, keystore, elasticsearch.yml)
#   src/platform/packages/shared/kbn-es/src/utils/native_realm.ts (user password setup)
set -euo pipefail

ES_VERSION="${ES_VERSION:-9.6.0}"
ES_PASSWORD="${ES_PASSWORD:-changeme}"
ES_LICENSE="${ES_LICENSE:-trial}"
ES_BASE_DIR="${ES_BASE_DIR:-${HOME}/.es}"
ES_CACHE_DIR="${ES_BASE_DIR}/cache"
ES_INSTALL_DIR="${ES_BASE_DIR}/install/${ES_VERSION}"

# Platform/arch mapping identical to artifact.ts lines 177-178
OS=$(uname -s | tr '[:upper:]' '[:lower:]')   # linux | darwin
case "$(uname -m)" in
  arm64|aarch64) ARCH="aarch64" ;;
  *)             ARCH="x86_64" ;;
esac

mkdir -p "$ES_CACHE_DIR" "$ES_INSTALL_DIR"

# ── Download, extract, and configure (skip entirely if already installed) ──────
if [[ ! -f "$ES_INSTALL_DIR/bin/elasticsearch" ]]; then
  # artifact.ts lines 150-164: daily manifest first, permanent as fallback
  echo "=== Resolving ES ${ES_VERSION} snapshot (${OS}-${ARCH}) ==="
  MANIFEST=$(curl -sf \
      "https://storage.googleapis.com/kibana-ci-es-snapshots-daily/${ES_VERSION}/manifest-latest-verified.json" \
    || curl -sf \
      "https://storage.googleapis.com/kibana-ci-es-snapshots-permanent/${ES_VERSION}/manifest.json")

  # artifact.ts line 180: match platform + arch + license='default'
  ARTIFACT_URL=$(echo "$MANIFEST" | python3 -c "
import json, sys
m = json.load(sys.stdin)
match = next(
  (a for a in m['archives']
   if a['platform'] == '$OS' and a['architecture'] == '$ARCH' and a['license'] == 'default'),
  None
)
if not match:
  print('No matching archive found', file=sys.stderr); sys.exit(1)
print(match['url'])
")

  FILENAME=$(basename "$ARTIFACT_URL")
  DEST="$ES_CACHE_DIR/$FILENAME"

  if [[ ! -f "$DEST" ]]; then
    echo "=== Downloading $FILENAME ==="
    curl -L --progress-bar -o "${DEST}.tmp" "$ARTIFACT_URL"

    echo "=== Verifying checksum ==="
    EXPECTED=$(curl -sf "${ARTIFACT_URL}.sha512" | awk '{print $1}')
    ACTUAL=$(sha512sum "${DEST}.tmp" | awk '{print $1}')
    if [[ "$EXPECTED" != "$ACTUAL" ]]; then
      echo "ERROR: Checksum mismatch"
      rm -f "${DEST}.tmp"
      exit 1
    fi
    mv "${DEST}.tmp" "$DEST"
  else
    echo "=== Using cached $FILENAME ==="
  fi

  echo "=== Extracting to $ES_INSTALL_DIR ==="
  tar xzf "$DEST" -C "$ES_INSTALL_DIR" --strip-components=1

  # install_archive.ts line 75: ES_TMPDIR directory
  mkdir -p "$ES_INSTALL_DIR/ES_TMPDIR"

  # install_archive.ts lines 81-83: append to elasticsearch.yml
  cat >> "$ES_INSTALL_DIR/config/elasticsearch.yml" <<EOF
xpack.security.enabled: true
xpack.license.self_generated.type: ${ES_LICENSE}
EOF

  # install_archive.ts lines 84-87: bootstrap keystore password
  # -xf: read from stdin (-x), force overwrite if key exists (-f)
  "$ES_INSTALL_DIR/bin/elasticsearch-keystore" create
  printf '%s' "$ES_PASSWORD" | "$ES_INSTALL_DIR/bin/elasticsearch-keystore" add -xf bootstrap.password
else
  echo "=== ES ${ES_VERSION} already installed, skipping download ==="
fi

# ── Start Elasticsearch ───────────────────────────────────────────────────────
echo "=== Starting Elasticsearch ${ES_VERSION} ==="

export JAVA_HOME=""
export ES_TMPDIR="$ES_INSTALL_DIR/ES_TMPDIR"
# cluster.ts lines 607-614: default heap if Xmx not already set
export ES_JAVA_OPTS="${ES_JAVA_OPTS:--Xms1536m -Xmx1536m}"

# cluster.ts lines 395-399: default -E flags always applied
# enrollment.enabled=false prevents ES 8+/9+ auto-configuration from overriding bootstrap.password
"$ES_INSTALL_DIR/bin/elasticsearch" \
  -E action.destructive_requires_name=true \
  -E cluster.routing.allocation.disk.threshold_enabled=false \
  -E ingest.geoip.downloader.enabled=false \
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
