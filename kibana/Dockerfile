FROM kibana-base:latest AS base

# ── Runtime ────────────────────────────────────────────────────────────────────
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

ARG KIBANA_BRANCH=main
ENV KIBANA_BRANCH=$KIBANA_BRANCH

RUN apt-get update && apt-get install -y \
    curl gettext-base \
    && rm -rf /var/lib/apt/lists/*

COPY --from=base /opt/kibana-dist /opt/kibana

RUN useradd -m -s /bin/bash kibana \
    && chown -R kibana:kibana /opt/kibana

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5601

USER kibana
ENTRYPOINT ["/entrypoint.sh"]
