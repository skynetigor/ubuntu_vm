# ── Stage 1: Build ────────────────────────────────────────────────────────────
FROM eclipse-temurin:21-jdk AS builder

ARG ES_TARGET=https://github.com/elastic/elasticsearch/tree/main

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

WORKDIR /es-src
# Parse ES_TARGET URL and clone the specified branch or commit
RUN OWNER_REPO=$(echo "$ES_TARGET" | sed -E 's|https://github\.com/([^/]+/[^/]+).*|\1|') && \
    FORK="https://github.com/$OWNER_REPO" && \
    if echo "$ES_TARGET" | grep -qE '/tree/'; then \
      BRANCH=$(echo "$ES_TARGET" | sed -E 's|.*/tree/(.+)|\1|') && \
      git clone --depth 1 --branch "$BRANCH" "$FORK" .; \
    elif echo "$ES_TARGET" | grep -qE '/commit/[0-9a-f]+'; then \
      COMMIT=$(echo "$ES_TARGET" | sed -E 's|.*/commit/([0-9a-f]+).*|\1|') && \
      git init && git remote add origin "$FORK" && \
      git fetch --depth 1 origin "$COMMIT" && \
      git checkout FETCH_HEAD; \
    else \
      echo "ERROR: ES_TARGET must be a branch URL (.../tree/<branch>) or commit URL (.../commit/<sha>)" && exit 1; \
    fi

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
