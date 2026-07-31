# kibana

Everything needed to clone, build, and run a Kibana development distribution inside Docker.

## Files

| File | Description |
|---|---|
| `scripts/` | Build scripts: clone → bootstrap → compile |
| `workflows/` | Kibana workflow definitions |
| `Dockerfile` | Kibana runtime image (copies pre-built dist, downloads matching Node binary) |
| `es.Dockerfile` | Elasticsearch image (downloads matching ES snapshot on first start) |
| `entrypoint.sh` | Kibana container entrypoint: sets kibana_system password, starts Kibana |
| `es-entrypoint.sh` | ES container entrypoint |
| `start-es.sh` | Downloads, configures, and starts the ES snapshot |
| `kibana.dev.yml` | Kibana config template (processed by `envsubst` at startup) |
| `docker-compose.yml` | ES + Kibana compose for standalone use or workflow-driven deployments |
| `run.sh` | Build from source and start the stack in one command |
| `build.sh` | Build from source only (no docker up) |

## Build pipeline

```
clone.sh → bootstrap.sh → compile.sh → docker compose up --build
```

Each stage writes a `.{stage}commit` marker to `dist/kibana/`. On the next run the stage is skipped if the repo HEAD matches the stored commit — making reruns fast.

## Usage

```bash
cd kibana

# Configure
cp .env.example .env   # fill in KIBANA_FORK, KIBANA_BRANCH, etc.

# Full build + start
bash run.sh

# Build only
bash build.sh

# Start pre-built stack (skip build)
docker compose up -d --build
```

## Environment variables (kibana/.env)

| Variable | Default | Description |
|---|---|---|
| `KIBANA_FORK` | `https://github.com/elastic/kibana` | Git URL to clone |
| `KIBANA_BRANCH` | `main` | Branch to build |
| `ES_VERSION` | `9.6.0` | Elasticsearch snapshot version |
| `ES_PASSWORD` | `changeme` | Password for `elastic` and `kibana_system` users |
| `ES_PORT` | `5002` | Host port for Elasticsearch (workflow sets this automatically) |
| `KIBANA_PORT` | `5601` | Host port for Kibana (workflow sets this automatically) |
| `KIBANA_PUBLIC_URL` | _(derived from port)_ | Public base URL shown in Kibana config |
| `NODE_VERSION` | _(from .nvmrc)_ | Written by compile.sh; used as Docker build arg |
| `LOCAL_DIR` | `dist` | Local directory for cloned source and compiled output |

## Kibana config

`kibana.dev.yml` is a template mounted into the container at `/etc/kibana-config/kibana.dev.yml`. The entrypoint runs `envsubst` over it to produce the final `kibana.yml`. Variables substituted: `${ES_PASSWORD}`, `${KIBANA_PUBLIC_URL}`, `${ES_HOST}`, `${KIBANA_BRANCH}`.
