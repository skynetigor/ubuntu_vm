# ── Stage 1: Clone ─────────────────────────────────────────────────────────────
FROM ubuntu:22.04 AS clone

ENV DEBIAN_FRONTEND=noninteractive

ARG KIBANA_REPO_URL=https://github.com/elastic/kibana
ARG KIBANA_BRANCH=main

RUN apt-get update && apt-get install -y git curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash builder
RUN git clone --depth 1 --branch "$KIBANA_BRANCH" "$KIBANA_REPO_URL" /opt/kibana-src \
    && chown -R builder:builder /opt/kibana-src

# ── Stage 2: Bootstrap ─────────────────────────────────────────────────────────
FROM ubuntu:22.04 AS bootstrap

ENV DEBIAN_FRONTEND=noninteractive \
    NVM_DIR=/opt/nvm

RUN apt-get update && apt-get install -y \
    curl build-essential python3 libsecret-1-dev \
    && rm -rf /var/lib/apt/lists/*

SHELL ["/bin/bash", "-c"]

RUN useradd -m -s /bin/bash builder
COPY --from=clone --chown=builder:builder /opt/kibana-src /opt/kibana-src
RUN mkdir -p "$NVM_DIR" && chown -R builder:builder "$NVM_DIR"

USER builder

RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash \
    && source "$NVM_DIR/nvm.sh" \
    && cd /opt/kibana-src \
    && nvm install \
    && nvm use \
    && npm install -g yarn \
    && KBN_BOOTSTRAP_NO_PREBUILT=true yarn kbn bootstrap

# ── Stage 3: Build ─────────────────────────────────────────────────────────────
FROM ubuntu:22.04 AS build

ENV DEBIAN_FRONTEND=noninteractive \
    NVM_DIR=/opt/nvm

RUN apt-get update && apt-get install -y \
    curl build-essential python3 libsecret-1-dev \
    && rm -rf /var/lib/apt/lists/*

SHELL ["/bin/bash", "-c"]

RUN useradd -m -s /bin/bash builder
COPY --from=bootstrap --chown=builder:builder /opt/kibana-src /opt/kibana-src
COPY --from=bootstrap --chown=builder:builder /opt/nvm /opt/nvm
RUN mkdir -p /opt/kibana-dist && chown builder:builder /opt/kibana-dist

USER builder

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

# ── Stage 4: Runtime ───────────────────────────────────────────────────────────
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

ARG KIBANA_BRANCH=main
ENV KIBANA_BRANCH=$KIBANA_BRANCH

RUN apt-get update && apt-get install -y \
    curl gettext-base \
    && rm -rf /var/lib/apt/lists/*

COPY --from=build /opt/kibana-dist /opt/kibana

RUN useradd -m -s /bin/bash kibana \
    && chown -R kibana:kibana /opt/kibana

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5601

USER kibana
ENTRYPOINT ["/entrypoint.sh"]
