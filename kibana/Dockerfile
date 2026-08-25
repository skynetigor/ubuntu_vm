FROM ubuntu:22.04

RUN apt-get update && apt-get install -y curl gettext-base openssh-client python3 python3-yaml && rm -rf /var/lib/apt/lists/*

# Create user before COPY so --chown can reference it
RUN useradd -m -s /bin/bash kibana

# dist is mounted as a volume at /opt/kibana at runtime — no COPY needed.
# scripts/ is mounted as a volume at /opt/kibana/setup/ at runtime.
# The COPY below is a fallback for environments without volume mounts.
COPY --chown=kibana:kibana scripts/ /opt/kibana/setup/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5601
USER kibana
ENTRYPOINT ["/entrypoint.sh"]
