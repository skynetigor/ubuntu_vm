#!/bin/bash
set -e

# Fix /root permissions (Windows bind mount sets 777)
chmod 750 /root
mkdir -p /root/.ssh && chmod 700 /root/.ssh

if [ -n "${SSH_KEYS_BASE64:-}" ]; then
  echo "$SSH_KEYS_BASE64" | base64 -d > /root/.ssh/authorized_keys
  mkdir -p /home/kibana/.ssh
  echo "$SSH_KEYS_BASE64" | base64 -d > /home/kibana/.ssh/authorized_keys
  chown -R kibana:kibana /home/kibana/.ssh
else
  cp /etc/ssh/authorized_keys.bak /root/.ssh/authorized_keys
fi
chmod 600 /root/.ssh/authorized_keys
chmod 600 /home/kibana/.ssh/authorized_keys 2>/dev/null || true

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
