FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
ENV NVM_DIR=/opt/nvm

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

# NVM + Node LTS + Yarn + Claude (system-wide at /opt/nvm)
RUN mkdir -p "$NVM_DIR" \
    && curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh \
       | NVM_DIR="$NVM_DIR" PROFILE=/dev/null bash \
    && . "$NVM_DIR/nvm.sh" \
    && nvm install --lts \
    && nvm alias default node \
    && npm install -g yarn @anthropic-ai/claude-code \
    # Symlink into /usr/local/bin so all shells (interactive and non-interactive) find them
    && NODE_BIN="$(dirname "$(nvm which default)")" \
    && ln -sf "$NODE_BIN/node"   /usr/local/bin/node \
    && ln -sf "$NODE_BIN/npm"    /usr/local/bin/npm \
    && ln -sf "$NODE_BIN/npx"    /usr/local/bin/npx \
    && ln -sf "$NODE_BIN/yarn"   /usr/local/bin/yarn \
    && ln -sf "$NODE_BIN/claude" /usr/local/bin/claude

# Make NVM available in all shell types:
#   /etc/profile.d  — login shells (ssh -l, su -, interactive login)
#   /etc/bash.bashrc — non-login interactive shells
#   /etc/environment — sets NVM_DIR for PAM-based sessions (non-interactive SSH)
RUN printf 'export NVM_DIR=/opt/nvm\n[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"\n' \
      > /etc/profile.d/nvm.sh \
    && printf '\nexport NVM_DIR=/opt/nvm\n[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"\n' \
      >> /etc/bash.bashrc \
    && echo 'NVM_DIR=/opt/nvm' >> /etc/environment

# User setup
RUN useradd -m -s /bin/bash kibana \
    && echo "kibana:kibana" | chpasswd \
    && usermod -aG sudo,docker kibana \
    && echo "kibana ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers \
    && mkdir -p /home/kibana/.ssh \
    && chmod 700 /home/kibana/.ssh \
    && chown -R kibana:kibana /opt

# NVM in kibana's bashrc (for non-login interactive shells opened after su)
RUN printf '\nexport NVM_DIR=/opt/nvm\n[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"\n' \
      >> /home/kibana/.bashrc

COPY id_ed25519.pub /home/kibana/.ssh/authorized_keys
RUN chmod 600 /home/kibana/.ssh/authorized_keys \
    && chown -R kibana:kibana /home/kibana/.ssh

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
