# Implementation Plan — Build ES from Source (replace snapshot)

## 1. Goal

- **Remove the ES snapshot** download entirely; Elasticsearch is built from source inside a **multi-stage Docker image**.
- **Mirror the Kibana pattern** — new `elasticsearch/` directory with `scripts/resolve.sh`, `Dockerfile`, `entrypoint.sh`.
- **Support any branch/commit** via `ES_TARGET` (branch URL / commit URL), resolved the same way Kibana does it.
- **Images tagged by commit SHA** (`es-local:<ES_COMMIT>`) are shared across all previews on the dev-vm; Docker's BuildKit cache handles the Gradle build cache between runs.
- **Data persists across container restarts and rebuilds** — the ES binary lives in the image; only the data directory is a named volume.

---

## 2. Target Directory Layout

```
ubuntu_vm/
├── elasticsearch/              # NEW — parallel to kibana/
│   ├── scripts/
│   │   └── resolve.sh          # parse ES_TARGET → ES_FORK, ES_BRANCH, ES_COMMIT
│   ├── Dockerfile              # multi-stage: eclipse-temurin:21-jdk builder + ubuntu:22.04 runtime
│   └── entrypoint.sh           # configure elasticsearch.yml, keystore, start ES, set up users/roles
├── kibana/
│   ├── docker-compose.yml      # MODIFY — elasticsearch service: image tag + build args, new volume path
│   ├── es.Dockerfile           # DELETE
│   ├── start-es.sh             # DELETE
│   ├── es-entrypoint.sh        # DELETE
│   └── ...
└── dev-env/
    ├── docker-compose.yml      # MODIFY — elasticsearch service: same changes
    └── workflows/
        └── deploy-kibana-preview.yaml  # MODIFY — new es_target input + resolve_es + build_es steps
```

---

## 3. New Environment Variables

| Var | Default | Meaning |
|---|---|---|
| `ES_TARGET` | `https://github.com/elastic/elasticsearch/tree/main` | GitHub URL (branch / commit) to clone and build |
| `ES_COMMIT` | _(resolved from `ES_TARGET`)_ | Full commit SHA — used as the Docker image tag |
| `ES_FORK` | `https://github.com/elastic/elasticsearch.git` | Clone URL, extracted from `ES_TARGET` |
| `ES_PASSWORD` | `changeme` | Password for the `elastic` user and all reserved users |
| `ES_LICENSE` | `trial` | License type passed to `xpack.license.self_generated.type` — kept from current setup |

**Dropped** (no longer needed): `ES_VERSION`, `ES_BASE_DIR`, `ES_CACHE_DIR`, `ES_INSTALL_DIR`.

---

## 4. Scope of Changes

| File | Change | Summary |
|---|---|---|
| `elasticsearch/scripts/resolve.sh` | add | Parse `ES_TARGET` → `ES_FORK`, `ES_BRANCH`, `ES_COMMIT` |
| `elasticsearch/Dockerfile` | add | Multi-stage: eclipse-temurin:21-jdk builder + ubuntu:22.04 runtime; no USER directive (root entrypoint) |
| `elasticsearch/entrypoint.sh` | add | Root entrypoint: chown data volume → exec su to `start-es.sh` (mirrors `es-entrypoint.sh` pattern) |
| `elasticsearch/start-es.sh` | add | Configure `elasticsearch.yml`, keystore, start with exact `-E` flags, wait, set up users/roles |
| `kibana/docker-compose.yml` | modify | `elasticsearch` service: `image: es-local:${ES_COMMIT}`, build args, new volume path, keep `ES_LICENSE` |
| `dev-env/docker-compose.yml` | modify | Same elasticsearch service changes |
| `dev-env/workflows/deploy-kibana-preview.yaml` | modify | Add `es_target` input; add `resolve_es`, `build_es` steps; update `write_env` with ES vars |
| `kibana/es.Dockerfile` | delete | Replaced by `elasticsearch/Dockerfile` |
| `kibana/start-es.sh` | delete | Replaced by `elasticsearch/start-es.sh` |
| `kibana/es-entrypoint.sh` | delete | Replaced by `elasticsearch/entrypoint.sh` |

**10 files total — 3 modify, 4 add, 3 delete.**

---

## 5. Files to Change

### 1. `elasticsearch/scripts/resolve.sh` (new)

Identical structure to `kibana/scripts/resolve.sh`, operating on `ES_*` variables:

```bash
ES_TARGET="${ES_TARGET:-https://github.com/elastic/elasticsearch/tree/main}"
# → sets ES_FORK (clone URL), ES_BRANCH, ES_COMMIT
```

Copy `kibana/scripts/resolve.sh` and replace all `KIBANA_` prefixes with `ES_` and update the default URL.

`PROJECT` is not needed here (ES has no per-deployment source tree — it's baked into the image).

---

### 2. `elasticsearch/Dockerfile` (new)

Multi-stage build. Stage 1 clones and builds; stage 2 is the lean runtime image.

```dockerfile
# ── Stage 1: Build ────────────────────────────────────────────────────────────
FROM eclipse-temurin:21-jdk AS builder

ARG ES_FORK=https://github.com/elastic/elasticsearch.git
ARG ES_COMMIT=main

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

WORKDIR /es-src
RUN git init && \
    git remote add origin "$ES_FORK" && \
    git fetch --depth 1 origin "$ES_COMMIT" && \
    git checkout FETCH_HEAD

# BuildKit cache mount keeps ~/.gradle across builds on the same Docker daemon
RUN --mount=type=cache,target=/root/.gradle \
    ./gradlew localDistro --no-daemon

# ── Stage 2: Runtime ──────────────────────────────────────────────────────────
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

RUN groupadd -g 1000 elasticsearch && \
    useradd -u 1000 -g elasticsearch -m -s /bin/bash elasticsearch

# Distro contains a bundled JDK — no separate Java install needed in runtime stage
COPY --from=builder /es-src/build/distribution/local/elasticsearch-*/ /opt/elasticsearch/
RUN chown -R elasticsearch:elasticsearch /opt/elasticsearch

COPY entrypoint.sh start-es.sh /
RUN chmod +x /entrypoint.sh /start-es.sh

VOLUME ["/var/lib/elasticsearch"]

EXPOSE 9200 9300

# No USER directive — entrypoint runs as root, chowns the data volume, then drops to elasticsearch
ENTRYPOINT ["/entrypoint.sh"]
```

**Key points:**
- `--mount=type=cache,target=/root/.gradle` — Gradle dependency cache preserved between Docker builds on the same daemon; first build ~1–2 GB download, subsequent builds fast.
- No `USER` directive — mirrors the current `es-entrypoint.sh` pattern (runs as root, `chown`s the volume, `exec su` to elasticsearch). Required because the mounted volume arrives as root-owned.
- The glob `elasticsearch-*/` in `COPY --from` works because only one directory is present.

---

### 3. `elasticsearch/entrypoint.sh` (new)

Mirrors `kibana/es-entrypoint.sh` exactly, updated for new paths:

```bash
#!/bin/bash
set -e
chown -R elasticsearch:elasticsearch /var/lib/elasticsearch
exec su -s /bin/bash elasticsearch -c "/start-es.sh"
```

---

### 4. `elasticsearch/start-es.sh` (new)

Replaces `kibana/start-es.sh`. The entire "download, verify, extract" section (lines 1–87) is removed — the binary is already at `/opt/elasticsearch`. Everything from line 89 onward is kept **verbatim**, with two path substitutions and two additions:

**Substitutions** (old → new):

| Variable | Old value | New value |
|---|---|---|
| `ES_HOME` | `$ES_INSTALL_DIR` (dynamic) | `/opt/elasticsearch` |
| `ES_TMPDIR` | `"$ES_INSTALL_DIR/ES_TMPDIR"` | `"$ES_HOME/ES_TMPDIR"` |

**Additions at the top** (before the "Start Elasticsearch" block):

```bash
ES_HOME=/opt/elasticsearch
ES_LICENSE="${ES_LICENSE:-trial}"
ES_DATA_DIR=/var/lib/elasticsearch/data
ES_LOGS_DIR=/var/lib/elasticsearch/logs

mkdir -p "$ES_DATA_DIR" "$ES_LOGS_DIR" "$ES_HOME/ES_TMPDIR"

# Append to elasticsearch.yml — same as start-es.sh lines 76-79, plus data/log paths
cat >> "$ES_HOME/config/elasticsearch.yml" <<EOF
path.data: ${ES_DATA_DIR}
path.logs: ${ES_LOGS_DIR}
xpack.security.enabled: true
xpack.license.self_generated.type: ${ES_LICENSE}
EOF

# Keystore bootstrap — identical to start-es.sh lines 83-84
"$ES_HOME/bin/elasticsearch-keystore" create
printf '%s' "$ES_PASSWORD" | "$ES_HOME/bin/elasticsearch-keystore" add -xf bootstrap.password
```

Then the rest — `export JAVA_HOME=""`, `export ES_TMPDIR`, `export ES_JAVA_OPTS`, the `elasticsearch` invocation with all `-E` flags, the wait loops, user/role setup — is **verbatim from `kibana/start-es.sh` lines 92–171**.

---

### 5. `kibana/docker-compose.yml` (modify)

```yaml
# BEFORE
elasticsearch:
  build:
    context: .
    dockerfile: es.Dockerfile
  environment:
    - ES_VERSION=${ES_VERSION:-9.6.0}
    - ES_PASSWORD=${ES_PASSWORD:-changeme}
    - ES_LICENSE=trial
    - ES_BASE_DIR=/es
  volumes:
    - es_data:/es
  start_period: 120s

# AFTER
elasticsearch:
  image: es-local:${ES_COMMIT:-main}
  build:
    context: ../elasticsearch
    dockerfile: Dockerfile
    args:
      ES_FORK: ${ES_FORK:-https://github.com/elastic/elasticsearch.git}
      ES_COMMIT: ${ES_COMMIT:-main}
  environment:
    - ES_PASSWORD=${ES_PASSWORD:-changeme}
    - ES_LICENSE=${ES_LICENSE:-trial}
  volumes:
    - es_data:/var/lib/elasticsearch
  start_period: 60s   # no download; JVM startup only
```

- Remove: `ES_VERSION`, `ES_BASE_DIR` from `environment`. Keep `ES_LICENSE` (used by `start-es.sh`).
- `image:` + `build:` together: use the tagged image if it exists (built by the workflow's `build_es` step); otherwise build it. `docker compose up --build` rebuilds but all layers are cached, so it's instant.

---

### 6. `dev-env/docker-compose.yml` (modify)

Same changes to the `elasticsearch` service:

```yaml
# BEFORE
elasticsearch:
  build:
    context: ../kibana
    dockerfile: es.Dockerfile
  environment:
    - ES_VERSION=${ES_VERSION:-9.6.0}
    - ES_PASSWORD=${ES_PASSWORD:-changeme}
    - ES_LICENSE=trial
    - ES_BASE_DIR=/es
  volumes:
    - es_data:/es

# AFTER
elasticsearch:
  image: es-local:${ES_COMMIT:-main}
  build:
    context: ../elasticsearch
    dockerfile: Dockerfile
    args:
      ES_FORK: ${ES_FORK:-https://github.com/elastic/elasticsearch.git}
      ES_COMMIT: ${ES_COMMIT:-main}
  environment:
    - ES_PASSWORD=${ES_PASSWORD:-changeme}
    - ES_LICENSE=${ES_LICENSE:-trial}
  volumes:
    - es_data:/var/lib/elasticsearch
```

`dev-env/start.sh` — **no change needed**. `docker compose up --build` already triggers the ES image build if the tag doesn't exist.

---

### 7. `dev-env/workflows/deploy-kibana-preview.yaml` (modify)

**a) New input** (under `triggers[0].inputs.properties`):

```yaml
es_target:
  type: string
  description: |
    GitHub URL for the Elasticsearch branch or commit to build. Formats:
      Branch — https://github.com/<owner>/<repo>/tree/<branch>
      Commit — https://github.com/<owner>/<repo>/commit/<sha>
  default: https://github.com/elastic/elasticsearch/tree/main
```

**b) New step `resolve_es`** (after `resolve`):

```yaml
- name: resolve_es
  type: remoteHost.runCommand
  connector-id: dev-vm
  with:
    env:
      ES_TARGET: '{{ inputs.es_target }}'
      SCRIPTS_CACHE: /opt/ubuntu_vm
    code: |
      source "$SCRIPTS_CACHE/elasticsearch/scripts/resolve.sh"
      echo "ES_COMMIT=$ES_COMMIT" >> $STEP_OUTPUT
      echo "ES_FORK=$ES_FORK" >> $STEP_OUTPUT
```

**c) Update `write_env` step** — add ES vars to `.env`:

```bash
echo "ES_TARGET=${ES_TARGET}" >> "$DEPLOY_DIR/kibana/env/.env"
echo "ES_COMMIT=${ES_COMMIT}" >> "$DEPLOY_DIR/kibana/env/.env"
echo "ES_FORK=${ES_FORK}" >> "$DEPLOY_DIR/kibana/env/.env"
# Remove the ES_VERSION line — no longer needed
```

**d) New step `build_es`** (after `write_kibana_config`, before `clone`):

```yaml
- name: build_es
  type: remoteHost.runCommand
  connector-id: dev-vm
  with:
    env:
      ES_COMMIT: '{{ steps.resolve_es.output.ES_COMMIT }}'
      ES_FORK: '{{ steps.resolve_es.output.ES_FORK }}'
      DEPLOY_DIR: '/opt/{{ steps.resolve.output.PROJECT }}'
    code: |
      ES_IMAGE="es-local:${ES_COMMIT}"
      if docker image inspect "$ES_IMAGE" >/dev/null 2>&1; then
        echo "=== Cache hit — image $ES_IMAGE already exists ==="
      else
        echo "=== Building $ES_IMAGE ==="
        DOCKER_BUILDKIT=1 docker build \
          --build-arg ES_FORK="$ES_FORK" \
          --build-arg ES_COMMIT="$ES_COMMIT" \
          -t "$ES_IMAGE" \
          "$DEPLOY_DIR/elasticsearch"
        echo "=== Build complete ==="
      fi
```

**e) `start` step** — no change. `docker compose up --build --wait kibana` uses the existing `es-local:$ES_COMMIT` image (all layers cached); only the Kibana image is effectively rebuilt.

---

### 8–10. Deletions

- `kibana/es.Dockerfile` — delete
- `kibana/start-es.sh` — delete
- `kibana/es-entrypoint.sh` — delete

---

## 6. Gaps / Open Questions

All gaps resolved.

### ~~G1~~ — Java on dev-vm
✅ Resolved: Not needed. The builder stage uses `eclipse-temurin:21-jdk` — Java stays inside the Docker build, never touches the dev-vm host.

### ~~G2~~ — Gradle cache on dev-vm
✅ Resolved: BuildKit `--mount=type=cache,target=/root/.gradle` persists the Gradle cache across image builds on the same Docker daemon. The dev-vm's Docker storage is on the `dev-vm-docker` named volume, so the cache survives restarts.

### ~~G3~~ — `es_data` volume migration
✅ Resolved: Data loss on migration is acceptable. Existing `es_data` volumes will be recreated on first deploy.

### ~~G4~~ — ES_TARGET default for previews
✅ Resolved: Default to `https://github.com/elastic/elasticsearch/tree/main`; user can override to any branch/commit via the `es_target` input.

### ~~G5~~ — Build time / caching across previews
✅ Resolved: Images tagged `es-local:<ES_COMMIT>` are shared — any preview using the same ES commit reuses the existing image instantly (`docker image inspect` guard in `build_es`). Gradle cache is preserved via BuildKit cache mount.

### ~~G6~~ — dev-env local start script
✅ Resolved: `dev-env/start.sh` needs no changes. `docker compose up --build` triggers the ES image build automatically if the tag doesn't exist.
