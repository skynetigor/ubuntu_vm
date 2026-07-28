# ── Stage 1: Build ─────────────────────────────────────────────────────────────
FROM ubuntu:22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive \
    NVM_DIR=/opt/nvm

ARG KIBANA_REPO_URL=https://github.com/elastic/kibana
ARG KIBANA_BRANCH=main

RUN apt-get update && apt-get install -y \
    git curl build-essential python3 libsecret-1-dev \
    && rm -rf /var/lib/apt/lists/*

SHELL ["/bin/bash", "-c"]

RUN mkdir -p "$NVM_DIR" \
    && curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash

RUN git clone --depth 1 --branch "$KIBANA_BRANCH" "$KIBANA_REPO_URL" /opt/kibana-src

RUN source "$NVM_DIR/nvm.sh" \
    && cd /opt/kibana-src \
    && nvm install \
    && nvm use \
    && npm install -g yarn \
    && KBN_BOOTSTRAP_NO_PREBUILT=true yarn kbn bootstrap --allow-root

# Produce the distributable (bundles Node.js, excludes dev deps).
# --skip-archives        no .tar.gz  (we copy the directory directly)
# --skip-os-packages     no rpm/deb
# --skip-cloud-dependencies-download  no beats/cloud deps
# --skip-cdn-assets      no CDN upload artefacts
RUN source "$NVM_DIR/nvm.sh" \
    && cd /opt/kibana-src \
    && nvm use \
    && node scripts/build \
        --skip-archives \
        --skip-os-packages \
        --skip-cloud-dependencies-download \
        --skip-cdn-assets \
    && BUILD_DIR=$(ls -d build/default/kibana-*/ | head -1) \
    && mv "$BUILD_DIR" /opt/kibana-dist

# ── Stage 2: Runtime ───────────────────────────────────────────────────────────
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

ARG KIBANA_BRANCH=main
ENV KIBANA_BRANCH=$KIBANA_BRANCH

# curl: ES health + kibana_system password setup
# gettext-base: envsubst for config template
RUN apt-get update && apt-get install -y \
    curl gettext-base \
    && rm -rf /var/lib/apt/lists/*

# Built Kibana includes its own Node.js under node/ — no nvm needed at runtime
COPY --from=builder /opt/kibana-dist /opt/kibana

RUN useradd -m -s /bin/bash kibana \
    && chown -R kibana:kibana /opt/kibana

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5601

USER kibana
ENTRYPOINT ["/entrypoint.sh"]
