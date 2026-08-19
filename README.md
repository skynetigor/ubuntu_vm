# ubuntu_vm

Docker-based development environment for building and running Kibana preview deployments. The setup consists of three services that can run together or independently:

| Service | Description |
|---|---|
| `dev-vm` | Privileged SSH dev box with Docker-in-Docker, used to build and host Kibana previews |
| `elasticsearch` | Elasticsearch snapshot (version auto-matched to the Kibana branch) |
| `kibana` | Pre-built Kibana dev distribution |

## Repository layout

```
ubuntu_vm/
├── dev-env/            # Docker Compose for the full local stack (dev-vm + ES + Kibana)
├── elastic_dev_vm/     # Dockerfile and entrypoint for the SSH dev box
└── kibana/             # Kibana build scripts, Docker images, and Kibana workflows
    ├── scripts/        # clone / bootstrap / compile scripts
    └── workflows/      # Kibana workflow definitions (deploy_kibana_vm.yaml)
```

## Quick start (local full stack)

**Prerequisites:** Docker Desktop, SSH key pair in `elastic_dev_vm/`.

```bash
# 1. Configure (optional — set KIBANA_TARGET to build a specific PR/branch/commit)
# e.g. echo 'KIBANA_TARGET=https://github.com/elastic/kibana/tree/my-branch' > kibana/.env

# 2. Build Kibana and start all services
bash dev-env/start.sh

# 3. SSH into the dev box
bash dev-env/ssh.sh
```

Services after startup:

| Service | Address |
|---|---|
| Dev VM (SSH) | `ssh -p 2222 kibana@localhost` |
| Elasticsearch | `http://localhost:5001` |
| Kibana | `http://localhost:5002` |

## Workflow-based deploy (inside the dev-vm)

The `kibana/workflows/deploy_kibana_vm.yaml` workflow can be triggered from a running Kibana instance to build and deploy additional Kibana previews inside the dev-vm. Each branch gets its own Docker Compose project and auto-assigned ports from the `5003–5999` range.

## Key environment variables

| Variable | Where | Description |
|---|---|---|
| `KIBANA_TARGET` | `kibana/.env` | GitHub URL to build — PR, branch, or commit (default: `elastic/kibana` main) |
| `ES_PASSWORD` | `kibana/.env` | Elasticsearch `elastic` user password (default: `changeme`) |
| `SSH_KEYS_BASE64` | shell / `.env` | Base64-encoded authorized public keys for the dev-vm |
| `KIBANA_SSH_PRIVATE_KEY_BASE64` | shell / `.env` | Base64-encoded private key for Kibana's remote host connector |
