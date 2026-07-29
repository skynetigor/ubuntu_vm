FROM ubuntu:22.04

RUN apt-get update && apt-get install -y curl gettext-base && rm -rf /var/lib/apt/lists/*

# dist/kibana is produced by build.sh
COPY dist/kibana/dist /opt/kibana

# The build runs on Mac (darwin-arm64) so the bundled Node is a darwin binary.
# Replace it with the linux-arm64 binary so it runs inside the Linux container.
ARG NODE_VERSION
RUN curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-arm64.tar.gz" \
       -o /tmp/node.tar.gz \
    && rm -rf /opt/kibana/node \
    && mkdir -p /opt/kibana/node/default \
    && tar xzf /tmp/node.tar.gz -C /opt/kibana/node/default --strip-components=1 \
    && rm /tmp/node.tar.gz

RUN useradd -m -s /bin/bash kibana \
    && chmod -R a+x /opt/kibana/bin /opt/kibana/node/default/bin \
    && chown -R kibana:kibana /opt/kibana

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5601
USER kibana
ENTRYPOINT ["/entrypoint.sh"]
