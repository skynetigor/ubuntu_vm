#!/bin/bash
set -e

# Fix /root permissions (Windows bind mount sets 777)
chmod 750 /root
mkdir -p /root/.ssh && chmod 700 /root/.ssh
cp /etc/ssh/authorized_keys.bak /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

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
