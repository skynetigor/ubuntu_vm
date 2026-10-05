#!/usr/bin/env bash
# Starts a Scout stateful test server in the background and waits until Kibana answers HTTP.
set -euo pipefail
: "${SOURCE_DIR:?SOURCE_DIR is required}" "${STEP_OUTPUT:?STEP_OUTPUT is required}"

KIBANA_PORT=${SCOUT_KIBANA_PORT:-5620}
ES_PORT=${SCOUT_ES_PORT:-9220}
TIMEOUT_SECONDS=${SCOUT_START_TIMEOUT_SECONDS:-2400}
STATE_DIR=/tmp/workflow-scout-server
PID_FILE=$STATE_DIR/pid

case "$SOURCE_DIR" in
  *..*|*[!A-Za-z0-9_./-]*) echo "Invalid SOURCE_DIR: $SOURCE_DIR" >&2; exit 1 ;;
esac
mkdir -p "$STATE_DIR"

# Workflow concurrency allows one owner at a time, so a leftover pid belongs to a crashed run.
if [[ -f $PID_FILE ]]; then
  echo "Stopping leftover Scout server"
  STEP_OUTPUT=/dev/null bash "$(dirname "$0")/stop_scout_server.sh"
fi

for port in "$KIBANA_PORT" "$ES_PORT"; do
  if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then
    echo "Port $port is already in use; cannot start Scout server" >&2
    exit 1
  fi
done

log="$STATE_DIR/scout-$(date +%Y%m%d%H%M%S).log"
cd "$SOURCE_DIR"
echo "Starting Scout server in $SOURCE_DIR (log: $log)"
setsid nohup node scripts/scout.js start-server --arch stateful --domain classic --serverConfigSet default \
  > "$log" 2>&1 < /dev/null &
pid=$!
echo "$pid" > "$PID_FILE"

tail -n +1 -f --pid="$pid" "$log" &
tail_pid=$!
trap 'kill "$tail_pid" 2>/dev/null || true' EXIT

kibana_url="http://localhost:$KIBANA_PORT"
deadline=$(( $(date +%s) + TIMEOUT_SECONDS ))
while true; do
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "Scout server exited before Kibana became ready" >&2
    rm -f "$PID_FILE"
    exit 1
  fi
  # Kibana answers 503 while starting; 200/302/401 mean the HTTP server is serving the app.
  code=$(curl -s -o /dev/null -m 10 -w '%{http_code}' "$kibana_url/api/status" || true)
  case "$code" in
    200|302|401) break ;;
  esac
  if (( $(date +%s) >= deadline )); then
    echo "Kibana did not become ready within ${TIMEOUT_SECONDS}s" >&2
    STEP_OUTPUT=/dev/null bash "$(dirname "$0")/stop_scout_server.sh"
    exit 1
  fi
  sleep 10
done

echo "Scout server ready at $kibana_url"
printf '{"kibana_url":"%s","es_url":"http://localhost:%s","pid":%s,"log_path":"%s"}' \
  "$kibana_url" "$ES_PORT" "$pid" "$log" > "$STEP_OUTPUT"
