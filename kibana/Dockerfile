FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    NVM_DIR=/root/.nvm

RUN apt-get update && apt-get install -y \
    git curl build-essential python3 \
    # native node module deps
    libsecret-1-dev \
    # Playwright / Chromium
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxcb1 libxkbcommon0 libx11-6 \
    libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    && rm -rf /var/lib/apt/lists/*

# Install nvm (node version is determined at runtime from .nvmrc in the repo)
RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Kibana dev server and Elasticsearch HTTP
EXPOSE 5601 9200

ENTRYPOINT ["/entrypoint.sh"]
