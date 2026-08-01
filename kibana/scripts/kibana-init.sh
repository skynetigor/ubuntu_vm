#!/bin/bash
set -euo pipefail

# Kibana post-start initialization. Runs after wait-kibana.sh confirms
# Kibana is accepting requests. Add user creation, space setup, etc. here.

KIBANA_URL="${KIBANA_URL:-http://localhost:5601}"
KIBANA_USERNAME="${KIBANA_USERNAME:-elastic}"
KIBANA_PASSWORD="${KIBANA_PASSWORD:-${ES_PASSWORD:-changeme}}"
