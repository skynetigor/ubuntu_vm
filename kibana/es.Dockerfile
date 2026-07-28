FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# curl: manifest + artifact download + API calls
# python3: JSON parsing (manifest, cluster health)
# sha512sum is in coreutils (pre-installed)
RUN apt-get update && apt-get install -y \
    curl python3 \
    && rm -rf /var/lib/apt/lists/*

# The downloaded ES snapshot bundles its own JDK — no Java needed here.
COPY start-es.sh /start-es.sh
RUN chmod +x /start-es.sh

EXPOSE 9200 9300

ENTRYPOINT ["/start-es.sh"]
