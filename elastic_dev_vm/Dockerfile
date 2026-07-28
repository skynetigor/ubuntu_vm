FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Base tools + git
RUN apt-get update && apt-get install -y \
    openssh-server \
    sudo \
    curl \
    wget \
    git \
    vim \
    nano \
    htop \
    net-tools \
    iputils-ping \
    iproute2 \
    dnsutils \
    build-essential \
    python3 \
    python3-pip \
    ca-certificates \
    gnupg \
    lsb-release \
    && rm -rf /var/lib/apt/lists/*

# Docker Engine
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
       > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y \
       docker-ce docker-ce-cli containerd.io \
       docker-buildx-plugin docker-compose-plugin \
    && rm -rf /var/lib/apt/lists/*

# GitHub CLI
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
       > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# NVM + Node.js LTS
ENV NVM_DIR=/root/.nvm
RUN curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash \
    && . "$NVM_DIR/nvm.sh" \
    && nvm install --lts \
    && nvm use --lts \
    && nvm alias default node \
    && ln -sf "$(. "$NVM_DIR/nvm.sh" && nvm which current)" /usr/local/bin/node \
    && ln -sf "$(. "$NVM_DIR/nvm.sh" && dirname $(nvm which current))/npm" /usr/local/bin/npm \
    && ln -sf "$(. "$NVM_DIR/nvm.sh" && dirname $(nvm which current))/npx" /usr/local/bin/npx

# Yarn + Claude Code CLI
RUN npm install -g yarn @anthropic-ai/claude-code

# Make nvm available in login shells (SSH sessions)
RUN printf 'export NVM_DIR="%s"\n[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"\n[ -s "$NVM_DIR/bash_completion" ] && . "$NVM_DIR/bash_completion"\n' \
      "$NVM_DIR" > /etc/profile.d/nvm.sh

# SSH setup
RUN mkdir -p /var/run/sshd /root/.ssh && chmod 700 /root/.ssh

COPY id_ed25519.pub /root/.ssh/authorized_keys
RUN chmod 600 /root/.ssh/authorized_keys

RUN sed -i \
    -e 's/#PermitRootLogin.*/PermitRootLogin yes/' \
    -e 's/#PasswordAuthentication yes/PasswordAuthentication no/' \
    -e 's/PasswordAuthentication yes/PasswordAuthentication no/' \
    -e 's/#PubkeyAuthentication.*/PubkeyAuthentication yes/' \
    /etc/ssh/sshd_config

RUN ssh-keygen -A

# Seed snapshot of /root — copied to the bind-mount volume on first start
RUN cp -a /root /etc/root-seed

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22

ENTRYPOINT ["/entrypoint.sh"]
