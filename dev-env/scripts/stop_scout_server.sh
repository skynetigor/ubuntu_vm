#!/usr/bin/env bash
# Stops the Scout server started by start_scout_server.sh; safe to run when nothing is running.
set -uo pipefail
: "${STEP_OUTPUT:?STEP_OUTPUT is required}"

PID_FILE=/tmp/workflow-scout-server/pid
status=not_running

if [[ -f $PID_FILE ]]; then
  pid=$(cat "$PID_FILE")
  if [[ $pid =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    echo "Stopping Scout server process group $pid"
    kill -TERM -- "-$pid" 2>/dev/null || true
    for _ in $(seq 1 60); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 1
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "Scout server did not stop after 60s; killing"
      kill -KILL -- "-$pid" 2>/dev/null || true
    fi
    status=stopped
  fi
  rm -f "$PID_FILE"
fi

echo "Scout server: $status"
printf '{"status":"%s"}' "$status" > "$STEP_OUTPUT"
