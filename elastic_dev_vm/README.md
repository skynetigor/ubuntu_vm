# elastic_dev_vm

Dockerfile and entrypoint for the SSH development box. The container runs a full Docker daemon inside (Docker-in-Docker) so that Kibana preview stacks can be built and started via SSH or the Kibana workflow engine.

## What's inside the image

| Tool | How installed |
|---|---|
| Docker Engine + Compose plugin | Docker's official apt repo |
| GitHub CLI (`gh`) | GitHub's official apt repo |
| NVM | `/opt/nvm` (system-wide) |
| Node.js LTS | Via NVM; symlinked into `/usr/local/bin` |
| Yarn, Claude Code | `npm install -g` under the NVM node |
| git, curl, build-essential, … | Ubuntu apt |

NVM is sourced in `/etc/profile.d/nvm.sh`, `/etc/bash.bashrc`, and `kibana`'s `.bashrc`, so `nvm`, `node`, `yarn`, and `claude` are available in all shell types (interactive and non-interactive SSH).

## Files

| File | Description |
|---|---|
| `Dockerfile` | Builds the dev-vm image |
| `entrypoint.sh` | Starts dockerd, sets up SSH authorized_keys, starts sshd |
| `docker-compose.yml` | Standalone compose (SSH only, no ES/Kibana siblings) |
| `id_ed25519` / `id_ed25519.pub` | Default SSH key pair (fallback when `SSH_KEYS_BASE64` is not set) |

## Environment variables

| Variable | Description |
|---|---|
| `SSH_KEYS_BASE64` | Base64-encoded authorized_keys content. Generate with: `base64 -w 0 authorized_keys`. Falls back to the baked-in `id_ed25519.pub` if unset. |

## Volumes

| Path | Purpose |
|---|---|
| `/root` | Bind-mounted from host so the root home persists across recreations |
| `/var/lib/docker` | Named volume — required to avoid overlay-on-overlay build failures |
| `/opt` | Named volume — persists NVM, `/opt/deploy`, and `/opt/deploy-ports` |

## Ports

| Port | Description |
|---|---|
| `22` | SSH (mapped to `2222` in dev-env compose, `3500` in standalone compose) |
| `5002–5999` | Forwarded to the host for workflow-deployed Kibana previews |
