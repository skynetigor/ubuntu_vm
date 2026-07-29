FROM ubuntu:22.04

RUN apt-get update && apt-get install -y curl gettext-base && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash kibana

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# /opt/kibana is mounted at runtime via docker-compose KIBANA_SRC volume
EXPOSE 5601

USER kibana
ENTRYPOINT ["/entrypoint.sh"]
