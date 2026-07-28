FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive \
    NVM_DIR=/root/.nvm

ARG KIBANA_REPO_URL=https://github.com/elastic/kibana
ARG KIBANA_BRANCH=main
ENV KIBANA_BRANCH=$KIBANA_BRANCH

RUN apt-get update && apt-get install -y \
    git curl build-essential python3 gettext-base \
    libsecret-1-dev \
    libglib2.0-0 libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxcb1 libxkbcommon0 libx11-6 \
    libxcomposite1 libxdamage1 libxext6 libxfixes3 libxrandr2 \
    libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    && rm -rf /var/lib/apt/lists/*

SHELL ["/bin/bash", "-c"]

# Install nvm
RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash

# Clone repo
RUN git clone --depth 1 --branch "$KIBANA_BRANCH" "$KIBANA_REPO_URL" /opt/kibana

# Install Node.js from .nvmrc and bootstrap
RUN source "$NVM_DIR/nvm.sh" \
    && cd /opt/kibana \
    && nvm install \
    && nvm use \
    && npm install -g yarn \
    && KBN_BOOTSTRAP_NO_PREBUILT=true yarn kbn bootstrap --allow-root

RUN useradd -m -s /bin/bash kibana \
    && chown -R kibana:kibana /opt/kibana \
    && chmod o+rx /root \
    && chmod -R o+rx /root/.nvm

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 5601 9200

ENTRYPOINT ["/entrypoint.sh"]
