#!/bin/bash
set -e

# Seed /root from image on first run (bind mount starts empty)
if [ ! -f /root/.initialized ]; then
    cp -a /etc/root-seed/. /root/
    touch /root/.initialized
fi
chmod 750 /root

# Start Docker daemon in background
dockerd --host=unix:///var/run/docker.sock &

# Wait for Docker to be ready (up to 30s)
echo "Waiting for Docker daemon..."
timeout 30 sh -c 'until docker info >/dev/null 2>&1; do sleep 1; done'
echo "Docker daemon ready."

# Start SSH daemon in foreground
exec /usr/sbin/sshd -D -e
