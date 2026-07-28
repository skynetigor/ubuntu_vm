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

RUN useradd -m -s /bin/bash builder \
    && chown -R builder:builder /opt/nvm
RUN git clone --depth 1 --branch "$KIBANA_BRANCH" "$KIBANA_REPO_URL" /opt/kibana-src \
    && chown -R builder:builder /opt/kibana-src

USER builder

RUN source "$NVM_DIR/nvm.sh" \
    && cd /opt/kibana-src \
    && nvm install \
    && nvm use \
    && npm install -g yarn \
    && KBN_BOOTSTRAP_NO_PREBUILT=true yarn kbn bootstrap

# node scripts/build bundles Node.js into the distributable, but it downloads it from
# an Elastic-internal GCP proxy (kibana-ci-proxy-cache). Pre-download from nodejs.org
# and place at the exact paths CreateArchivesSources expects, then use --skip-initialize
# so the build skips DownloadNodeBuilds / VerifyExistingNodeBuilds entirely.
# Both 'default' and 'glibc-217' variants use the same standard binary here — the
# glibc-217 variant only matters on systems with glibc < 2.17 (Ubuntu 22.04 has 2.35).
RUN NODE_VERSION=$(cat /opt/kibana-src/.nvmrc) \
    && TARBALL="node-v${NODE_VERSION}-linux-x64.tar.gz" \
    && curl -fL "https://nodejs.org/dist/v${NODE_VERSION}/${TARBALL}" -o "/tmp/${TARBALL}" \
    && for VARIANT in default glibc-217; do \
         mkdir -p "/opt/kibana-src/.node_binaries/${NODE_VERSION}/${VARIANT}/linux-x64/extract"; \
         tar xzf "/tmp/${TARBALL}" \
           -C "/opt/kibana-src/.node_binaries/${NODE_VERSION}/${VARIANT}/linux-x64/extract" \
           --strip-components=1; \
       done \
    && rm "/tmp/${TARBALL}"

# --skip-initialize  skip DownloadNodeBuilds/VerifyExistingNodeBuilds (handled above)
# --skip-archives    no .tar.gz (we copy the directory directly)
# --skip-os-packages no rpm/deb
# --skip-cloud-dependencies-download  no beats/cloud deps
# --skip-cdn-assets  no CDN upload artefacts
RUN source "$NVM_DIR/nvm.sh" \
    && cd /opt/kibana-src \
    && nvm use \
    && node scripts/build \
        --skip-initialize \
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
