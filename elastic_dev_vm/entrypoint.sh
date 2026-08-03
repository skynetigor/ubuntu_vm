#!/bin/bash
set -e

# Export container env vars (injected by Docker from env_file/environment:) to
# /etc/environment so PAM makes them available to all SSH sessions.
env | grep -E '^[A-Za-z_][A-Za-z0-9_]*=' | grep -v '^(HOSTNAME|HOME|PATH|TERM|PWD|SHLVL|_)=' \
  >> /etc/environment

if [ -n "${SSH_KEYS_BASE64:-}" ]; then
  mkdir -p /home/kibana/.ssh
  echo "$SSH_KEYS_BASE64" | base64 -d > /home/kibana/.ssh/authorized_keys
  chmod 600 /home/kibana/.ssh/authorized_keys
  chown -R kibana:kibana /home/kibana/.ssh
fi

# Required for Elasticsearch
sysctl -w vm.max_map_count=262144

# Start Docker daemon in background
dockerd --host=unix:///var/run/docker.sock &

# Wait for Docker to be ready (up to 30s)
echo "Waiting for Docker daemon..."
timeout 30 sh -c 'until docker info >/dev/null 2>&1; do sleep 1; done'
echo "Docker daemon ready."

# Start SSH daemon in foreground
exec /usr/sbin/sshd -D -e
