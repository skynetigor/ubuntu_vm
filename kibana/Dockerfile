FROM ubuntu:22.04

RUN apt-get update && apt-get install -y curl gettext-base openssh-client python3 python3-yaml && rm -rf /var/lib/apt/lists/*

# Create user before COPY so --chown can reference it
RUN useradd -m -s /bin/bash kibana

# --chown sets ownership in one pass (no recursive chown needed after)
# --link decouples this layer from previous ones so BuildKit can cache it independently
COPY --chown=kibana:kibana dist /opt/kibana

# The dist bundles a darwin Node binary — replace it with the correct linux binary.
# Arch is detected at build time: aarch64 → arm64, x86_64 → x64.
COPY .nvmrc .nvmrc
RUN NODE_VERSION=$(cat .nvmrc) \
    && ARCH=$(uname -m | sed 's/aarch64/arm64/;s/x86_64/x64/') \
    && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${ARCH}.tar.gz" \
       -o /tmp/node.tar.gz \
    && rm -rf /opt/kibana/node \
    && mkdir -p /opt/kibana/node/default \
    && tar xzf /tmp/node.tar.gz -C /opt/kibana/node/default --strip-components=1 \
    && rm /tmp/node.tar.gz \
    && chown -R kibana:kibana /opt/kibana/node \
    && chmod +x /opt/kibana/bin/* /opt/kibana/node/default/bin/*

COPY --chown=kibana:kibana scripts/ /opt/kibana/setup/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5601
USER kibana
ENTRYPOINT ["/entrypoint.sh"]
