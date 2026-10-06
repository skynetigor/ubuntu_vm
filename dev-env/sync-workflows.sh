#!/usr/bin/env bash
# Upserts dev-env/workflows into the running Kibana without restarting it.
set -euo pipefail

DEV_ENV_DIR="$(cd "$(dirname "$0")" && pwd)"
set -a; source "$DEV_ENV_DIR/env/es.env"; set +a

docker compose -f "$DEV_ENV_DIR/docker-compose.yml" exec -T \
  -e WORKFLOWS_DIR=/opt/kibana/setup/workflows -e ES_PASSWORD="$ES_PASSWORD" kibana \
  sh -c 'cd /opt/kibana/setup && /opt/kibana/node/default/bin/node upload_workflows.js'
