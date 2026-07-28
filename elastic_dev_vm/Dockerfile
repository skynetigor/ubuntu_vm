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

# Node.js LTS (system-wide via NodeSource, unaffected by /root volume mount)
RUN curl -fsSL https://deb.nodesource.com/setup_lts.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Yarn + Claude Code CLI
RUN npm install -g --allow-scripts yarn @anthropic-ai/claude-code

# User setup
RUN useradd -m -s /bin/bash skynet_igor \
    && echo "skynet_igor:skynet_igor" | chpasswd \
    && usermod -aG sudo,docker skynet_igor \
    && echo "skynet_igor ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers \
    && mkdir -p /home/skynet_igor/.ssh \
    && chmod 700 /home/skynet_igor/.ssh

COPY id_ed25519.pub /home/skynet_igor/.ssh/authorized_keys
RUN chmod 600 /home/skynet_igor/.ssh/authorized_keys \
    && chown -R skynet_igor:skynet_igor /home/skynet_igor/.ssh

# SSH setup
RUN mkdir -p /var/run/sshd /root/.ssh && chmod 700 /root/.ssh

COPY id_ed25519.pub /etc/ssh/authorized_keys.bak
RUN chmod 600 /etc/ssh/authorized_keys.bak

RUN sed -i \
    -e 's/#PermitRootLogin.*/PermitRootLogin yes/' \
    -e 's/#PasswordAuthentication yes/PasswordAuthentication no/' \
    -e 's/PasswordAuthentication yes/PasswordAuthentication no/' \
    -e 's/#PubkeyAuthentication.*/PubkeyAuthentication yes/' \
    /etc/ssh/sshd_config

RUN ssh-keygen -A

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22

ENTRYPOINT ["/entrypoint.sh"]
