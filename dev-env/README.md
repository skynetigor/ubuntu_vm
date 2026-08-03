# dev-env

Docker Compose setup that runs the full local development stack: the SSH dev box, Elasticsearch, and Kibana as sibling containers on a shared network.

## Files

| File | Description |
|---|---|
| `docker-compose.yml` | Defines all four services (`dev-vm`, `elasticsearch`, `kibana`, `cloudflared`) |
| `start.sh` | Builds Kibana from source, then brings up the stack |
| `ssh.sh` | Opens an SSH session into the dev-vm |

## Usage

```bash
# Start everything (builds Kibana first)
bash dev-env/start.sh

# Start only infrastructure (skip Kibana build)
docker compose -f dev-env/docker-compose.yml up -d

# SSH into the dev box
bash dev-env/ssh.sh

# Tear down
docker compose -f dev-env/docker-compose.yml down
```

## Ports

| Service | Host port | Notes |
|---|---|---|
| Dev VM (SSH) | `2222` | `ssh -i elastic_dev_vm/id_ed25519 -p 2222 kibana@localhost` |
| Elasticsearch | `5001` | HTTP, no TLS |
| Kibana | `5002` | |
| Dev-VM forwarded range | `5003–5999` | Used by workflow-deployed previews inside the VM |

## Volumes

| Volume | Mounted at | Purpose |
|---|---|---|
| `DEV_VM_HOME` (bind) | `/root` | Persists root home across container recreations |
| `dev-vm-docker` | `/var/lib/docker` | Inner Docker layer cache (avoids overlay-on-overlay) |
| `dev-vm-opt` | `/opt` | Persists NVM, `/opt/deploy`, `/opt/deploy-ports` |
| `es_data` | `/es` | Elasticsearch data and downloaded snapshot cache |

## Environment variables

Create a `kibana/.env` file (see `kibana/README.md`). The compose file also reads:

| Variable | Default | Description |
|---|---|---|
| `DEV_VM_HOME` | `~/docker-files/elastic-dev-vm/home` | Host path bind-mounted to `/root` in dev-vm |
| `SSH_KEYS_BASE64` | _(empty)_ | Base64-encoded authorized_keys; falls back to baked-in key |
| `KIBANA_SSH_PRIVATE_KEY_BASE64` | _(empty)_ | Base64-encoded private key written to `/opt/kibana/config/dev-vm-key` |
| `KIBANA_PUBLIC_URL` | `http://localhost:5601` | Kibana's externally reachable URL |
| `CF_TUNNEL_TOKEN` | _(required for cloudflared)_ | Token from the Cloudflare Zero Trust dashboard |
| `CF_API_TOKEN` | _(required for register-tunnel.sh)_ | API token with Tunnel:Edit permission |
| `CF_ACCOUNT_ID` | _(required for register-tunnel.sh)_ | Cloudflare account ID (dashboard right sidebar) |
| `CF_TUNNEL_ID` | _(required for register-tunnel.sh)_ | Tunnel ID (Zero Trust → Networks → Tunnels) |
| `CF_HOSTNAME` | _(required for register-tunnel.sh)_ | Public hostname to register, e.g. `wf.skynetapp.dev` |
| `CF_SERVICE_URL` | _(required for register-tunnel.sh)_ | Backend URL, e.g. `http://kibana:5601` |
