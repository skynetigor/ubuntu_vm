FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    curl python3 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash elasticsearch

COPY start-es.sh /start-es.sh
COPY es-entrypoint.sh /es-entrypoint.sh
RUN chmod +x /start-es.sh /es-entrypoint.sh

EXPOSE 9200 9300

ENTRYPOINT ["/es-entrypoint.sh"]
