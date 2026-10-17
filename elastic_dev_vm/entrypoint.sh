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

# A restarted container (as opposed to a recreated one) keeps its filesystem, so the pid and socket files of the
# previous dockerd are still there. A fresh process tree hands dockerd the same PID again, which then looks like
# "process with PID 19 is still running", the daemon refuses to start, and the container restarts in a loop.
# Nothing can be running at this point, so the files are always stale.
rm -f /var/run/docker.pid /var/run/docker.sock /var/run/docker/containerd/containerd.pid

# Start Docker daemon in background
dockerd --host=unix:///var/run/docker.sock &

# Wait for Docker to be ready (up to 30s). A daemon that does not come up must not keep sshd from starting:
# SSH is how the VM is reached to look at the problem, and `set -e` would otherwise end the container here.
echo "Waiting for Docker daemon..."
if timeout 30 sh -c 'until docker info >/dev/null 2>&1; do sleep 1; done'; then
  echo "Docker daemon ready."
else
  echo "WARNING: the Docker daemon is not ready after 30s, starting sshd anyway." >&2
fi

# Start SSH daemon in foreground
exec /usr/sbin/sshd -D -e
