FROM ubuntu:22.04

RUN apt-get update && apt-get install -y curl gettext-base && rm -rf /var/lib/apt/lists/*

# Create user before COPY so --chown can reference it
RUN useradd -m -s /bin/bash kibana

# --chown sets ownership in one pass (no recursive chown needed after)
# --link decouples this layer from previous ones so BuildKit can cache it independently
COPY --chown=kibana:kibana dist/kibana/dist /opt/kibana

# The build runs on Mac (darwin-arm64) so the bundled Node is a darwin binary.
# Replace it with the linux-arm64 binary so it runs inside the Linux container.
ARG NODE_VERSION
RUN curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-arm64.tar.gz" \
       -o /tmp/node.tar.gz \
    && rm -rf /opt/kibana/node \
    && mkdir -p /opt/kibana/node/default \
    && tar xzf /tmp/node.tar.gz -C /opt/kibana/node/default --strip-components=1 \
    && rm /tmp/node.tar.gz \
    && chown -R kibana:kibana /opt/kibana/node \
    && chmod +x /opt/kibana/bin/* /opt/kibana/node/default/bin/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5601
USER kibana
ENTRYPOINT ["/entrypoint.sh"]
