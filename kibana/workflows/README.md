# kibana/workflows

Kibana workflow definitions for automated operations on the dev-vm.

## deploy_kibana_vm.yaml

Builds and deploys a Kibana preview inside the dev-vm for a given fork and branch. Multiple branches can run simultaneously — each gets its own Docker Compose project name and an auto-assigned port pair.

### Inputs

| Input | Default | Description |
|---|---|---|
| `kibana_fork` | `https://github.com/elastic/kibana` | Git URL of the Kibana fork to build |
| `kibana_branch` | `main` | Branch to build and deploy |

### Steps

| Step | What it does |
|---|---|
| `setup` | Clones or updates `ubuntu_vm` to `/opt/deploy`; auto-assigns free ports from `5003–5999`; writes `kibana/.env` |
| `clone` | Runs `clone.sh` — clones or updates the Kibana source |
| `bootstrap` | Runs `bootstrap.sh` — installs dependencies (skipped if already at current commit) |
| `compile` | Runs `compile.sh` — builds the distribution (skipped if already at current commit) |
| `start` | Runs `docker compose -p <project> up --build -d` |
| `summary` | Prints fork, branch, ES port, and Kibana URL |

### Port assignment

Ports are auto-assigned from `5003–5999` (5001–5002 are reserved for the main dev-env stack). Assignments are stored in `/opt/deploy-ports/<project>` and reused on re-deploy, so the same branch always gets the same ports.

### Connector

All steps run on the `dev-vm` remote host connector. The connector must be configured in Kibana with the dev-vm's SSH host, user, and private key (available at `/opt/kibana/config/dev-vm-key` if `KIBANA_SSH_PRIVATE_KEY_BASE64` is set).
