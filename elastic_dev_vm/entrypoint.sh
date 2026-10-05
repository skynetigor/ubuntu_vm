#!/bin/bash
set -e

install -d -m 0755 -o kibana -g kibana /opt/kibana-cache

if [ -n "${SSH_KEYS_BASE64:-}" ]; then
  mkdir -p /home/kibana/.ssh
  echo "$SSH_KEYS_BASE64" | base64 -d > /home/kibana/.ssh/authorized_keys
  chmod 600 /home/kibana/.ssh/authorized_keys
  chown -R kibana:kibana /home/kibana/.ssh
fi

# Expose Cloudflare and Claude Code vars to SSH sessions via PAM /etc/environment
if [ -f /etc/dev-env/cloudflare.env ] || [ -f /etc/dev-env/claude.env ]; then
  {
    for env_file in /etc/dev-env/cloudflare.env /etc/dev-env/claude.env; do
      if [ -f "$env_file" ]; then
        grep -v '^#' "$env_file" | grep -v '^$' || true
      fi
    done
  } > /etc/environment
  chmod 600 /etc/environment
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
