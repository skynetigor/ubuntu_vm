# Plan — Per-Deployment Directory Structure

## Goal

Each preview deployment gets its own fully self-contained directory at
`/opt/<project>/` containing both the ubuntu_vm repo clone and the Kibana
source + built dist. No shared `/opt/kibana_repo`.

```
/opt/<project>/               ← ubuntu_vm repo clone (was /opt/deployments/<project>/)
  kibana/
    src/                      ← Kibana source clone (was /opt/kibana_repo)
      dist/                   ← build output (compile.sh writes here)
    dist/                     ← volume source (hard-linked from src/dist or cache)
    docker-compose.yml
    env/.env
    scripts/
    workflows/
```

---

## Files Changed

| File | Changes |
|---|---|
| `dev-env/workflows/deploy-kibana-preview.yaml` | 10 targeted edits (see below) |
| `dev-env/workflows/cleanup-preview.yaml` | 2 edits — use `deploy_dir` from index instead of constructing path |

---

## Changes — `deploy-kibana-preview.yaml`

### 1. `setup_deployment` step

```bash
# before
DEPLOY_DIR="/opt/deployments/$PROJECT"
sudo mkdir -p "$DEPLOY_DIR" /opt/kibana_repo
sudo chown kibana:kibana "$DEPLOY_DIR" /opt/kibana_repo

# after
DEPLOY_DIR="/opt/$PROJECT"
sudo mkdir -p "$DEPLOY_DIR"
sudo chown kibana:kibana "$DEPLOY_DIR"
```

Remove the shared `/opt/kibana_repo` setup entirely.

---

### 2. `write_env` step

Three changes:

**a)** Path of `DEPLOY_DIR`:
```bash
# before
DEPLOY_DIR="/opt/deployments/$PROJECT"

# after
DEPLOY_DIR="/opt/$PROJECT"
```

**b)** `KIBANA_SRC` in written `.env`:
```bash
# before
echo "KIBANA_SRC=/opt/kibana_repo"

# after
echo "KIBANA_SRC=$DEPLOY_DIR/kibana/src"
```

**c)** Add `KIBANA_DIST` and `SCRIPTS_DIR` to the written `.env` (needed by the docker-compose volume mounts):
```bash
echo "KIBANA_DIST=$DEPLOY_DIR/kibana/dist"
echo "SCRIPTS_DIR=$DEPLOY_DIR/kibana/scripts"
```

---

### 3. `write_kibana_config` step

```js
// before
const envFile = `/opt/deployments/${project}/kibana/env/.env`;

// after
const envFile = `/opt/${project}/kibana/env/.env`;
```

---

### 4. `clone` step

```bash
# before
DEPLOY_DIR="/opt/deployments/{{ steps.resolve.output.PROJECT }}"
export KIBANA_SRC=/opt/kibana_repo

# after
DEPLOY_DIR="/opt/{{ steps.resolve.output.PROJECT }}"
export KIBANA_SRC="$DEPLOY_DIR/kibana/src"
```

---

### 5. `bootstrap` step

```bash
# before
DEPLOY_DIR="/opt/deployments/{{ steps.resolve.output.PROJECT }}"
export KIBANA_SRC=/opt/kibana_repo

# after
DEPLOY_DIR="/opt/{{ steps.resolve.output.PROJECT }}"
export KIBANA_SRC="$DEPLOY_DIR/kibana/src"
```

---

### 6. `compile` step

```bash
# before
DEPLOY_DIR="/opt/deployments/{{ steps.resolve.output.PROJECT }}"
export KIBANA_SRC=/opt/kibana_repo

# after
DEPLOY_DIR="/opt/{{ steps.resolve.output.PROJECT }}"
export KIBANA_SRC="$DEPLOY_DIR/kibana/src"
```

`compile.sh` already writes the built dist to `$KIBANA_SRC/dist/` — no changes
needed to the script itself.

---

### 7. `start` step

```bash
# before
DEPLOY_DIR="/opt/deployments/$PROJECT"
rm -rf "$DEPLOY_DIR/kibana/dist"
cp -al /opt/kibana_repo/dist "$DEPLOY_DIR/kibana/dist"

# after
DEPLOY_DIR="/opt/$PROJECT"
# dist copy removed — compile step (with cache logic) already creates
# $DEPLOY_DIR/kibana/dist, and it is mounted as a volume into the container.
```

`docker compose build` is still needed (for image changes: scripts, entrypoint,
OS packages) but is now much faster — no dist COPY, no node binary download.

All other `docker compose` references in this step already use `$DEPLOY_DIR` —
they just need the `DEPLOY_DIR` line updated.

---

### 8. Remaining steps (`upload_workflows`, `register_tunnel`, `get_container_logs`, `get_setup_logs`, `summary`)

Every step that contains:
```bash
DEPLOY_DIR="/opt/deployments/{{ steps.resolve.output.PROJECT }}"
# or
DEPLOY_DIR="/opt/deployments/$PROJECT"
```
changes to `/opt/...` without `deployments/`.

---

### 9. `index_deployment` step

```yaml
# before
deploy_dir_name: '{{ steps.resolve.output.PROJECT }}'

# after
deploy_dir: '/opt/{{ steps.resolve.output.PROJECT }}'
```

Remove `deploy_dir_name` — it was just the project name, already covered by
`container_name`.

---

### 10. `ensure_deployments_index` step

Add two missing mapping fields:
```yaml
deploy_dir:
  type: keyword
es_port:
  type: integer
```

(`es_port` was added to the document in a previous commit but never added to
the mapping.)

---

## Changes — `cleanup-preview.yaml`

`cleanup-preview.yaml` currently reconstructs the path as
`/opt/deployments/<deploy_dir_name>`. After this change it reads `deploy_dir`
directly from the index (the full absolute path stored by `index_deployment`).

### Teardown step (docker-compose down)

```bash
# before
DEPLOY_DIR="/opt/deployments/{{ steps.fetch_deployment.output._source.deploy_dir_name }}"

# after
DEPLOY_DIR="{{ steps.fetch_deployment.output._source.deploy_dir }}"
```

### Delete step (rm -rf)

```bash
# before
DEPLOY_DIR="/opt/deployments/{{ steps.fetch_deployment.output._source.deploy_dir_name }}"
if [ -d "$DEPLOY_DIR" ]; then
  rm -rf "$DEPLOY_DIR"
  ...
fi

# after
DEPLOY_DIR="{{ steps.fetch_deployment.output._source.deploy_dir }}"
if [ -d "$DEPLOY_DIR" ]; then
  rm -rf "$DEPLOY_DIR"   # removes /opt/<project>/ — ubuntu_vm clone, kibana/src, kibana/dist
  ...
fi
```

This removes the entire `/opt/<project>/` tree including the Kibana source and
built dist, which are now per-deployment rather than shared.

Note: if `node_modules` was a symlink into `/opt/kibana-cache/`, removing the
deployment dir removes the symlink but leaves the cache entry intact — correct
behaviour. Cache eviction is handled separately (see Cache eviction section).

---

## Shared Bootstrap + Compile Cache

The deploy workflow runs with `strategy: queue` — only one deployment executes
at a time, so no locking is needed.

### Cache layout on dev-vm

```
/opt/kibana-cache/
  <commit-sha>/
    node_modules/     ← yarn kbn bootstrap output (reused across deployments at same commit)
    dist/             ← compiled Kibana dist (reused across deployments at same commit)
```

### Changes to `bootstrap` step

`KIBANA_COMMIT` comes from `{{ steps.resolve.output.KIBANA_COMMIT }}` (set alongside `DEPLOY_DIR` and `KIBANA_SRC` at the top of the step). Before running `bootstrap.sh`, check the cache:

```bash
DEPLOY_DIR="/opt/{{ steps.resolve.output.PROJECT }}"
KIBANA_COMMIT="{{ steps.resolve.output.KIBANA_COMMIT }}"
export KIBANA_SRC="$DEPLOY_DIR/kibana/src"

CACHE_DIR="/opt/kibana-cache/$KIBANA_COMMIT"
if [ -d "$CACHE_DIR/node_modules" ]; then
  echo "=== Cache hit — symlinking node_modules ($KIBANA_COMMIT) ==="
  ln -sfn "$CACHE_DIR/node_modules" "$DEPLOY_DIR/kibana/src/node_modules"
else
  bash "$DEPLOY_DIR/kibana/scripts/bootstrap.sh"
  mkdir -p "$CACHE_DIR"
  cp -al "$DEPLOY_DIR/kibana/src/node_modules" "$CACHE_DIR/node_modules"
fi
```

### Changes to `compile` step

Before running `compile.sh`, check the cache:

```bash
DEPLOY_DIR="/opt/{{ steps.resolve.output.PROJECT }}"
KIBANA_COMMIT="{{ steps.resolve.output.KIBANA_COMMIT }}"
export KIBANA_SRC="$DEPLOY_DIR/kibana/src"

CACHE_DIR="/opt/kibana-cache/$KIBANA_COMMIT"
if [ -d "$CACHE_DIR/dist" ]; then
  echo "=== Cache hit — hard-linking dist ($KIBANA_COMMIT) ==="
  rm -rf "$DEPLOY_DIR/kibana/dist"
  cp -al "$CACHE_DIR/dist" "$DEPLOY_DIR/kibana/dist"
else
  bash "$DEPLOY_DIR/kibana/scripts/compile.sh"
  mkdir -p "$CACHE_DIR"
  cp -al "$DEPLOY_DIR/kibana/src/dist" "$CACHE_DIR/dist"
  cp -al "$DEPLOY_DIR/kibana/src/dist" "$DEPLOY_DIR/kibana/dist"
fi
```

### Cache eviction

The cache is not automatically evicted — old commit entries accumulate.
The `docker_prune` step in `cleanup-expired-previews.yaml` handles Docker
resources; a separate cache cleanup (e.g. `find /opt/kibana-cache -maxdepth 1
-mtime +7 -exec rm -rf {} +`) can be added to the same workflow to remove
cache entries older than N days.

---

## Trade-offs

| | Before | After |
|---|---|---|
| Disk per deployment | ubuntu_vm clone only (~MB) | ubuntu_vm + Kibana src + dist (~GB) |
| Concurrent deploys | Contend over `/opt/kibana_repo` | Fully isolated |
| Bootstrap/compile cache | Shared `/opt/kibana_repo` (implicit) | Shared `/opt/kibana-cache/<commit>/` — cache hit skips bootstrap+compile entirely |
| Cleanup | Remove `/opt/deployments/$PROJECT` | Remove `/opt/$PROJECT` |
