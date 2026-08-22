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

# User setup (before NVM so /home/kibana exists)
RUN useradd -m -s /bin/bash kibana \
    && echo "kibana:kibana" | chpasswd \
    && usermod -aG sudo,docker kibana \
    && echo "kibana ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers \
    && mkdir -p /home/kibana/.ssh \
    && chmod 700 /home/kibana/.ssh

# NVM + Node LTS + Yarn + Claude (in kibana's home — never in a named volume)
ENV NVM_DIR=/home/kibana/.nvm
RUN mkdir -p "$NVM_DIR" \
    && curl -fsSL https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.3/install.sh \
       | NVM_DIR="$NVM_DIR" PROFILE=/dev/null bash \
    && . "$NVM_DIR/nvm.sh" \
    && nvm install --lts \
    && nvm alias default node \
    && npm install -g yarn @anthropic-ai/claude-code \
    # Symlink into /usr/local/bin so all shells find them without sourcing nvm
    && NODE_BIN="$(dirname "$(nvm which default)")" \
    && ln -sf "$NODE_BIN/node"   /usr/local/bin/node \
    && ln -sf "$NODE_BIN/npm"    /usr/local/bin/npm \
    && ln -sf "$NODE_BIN/npx"    /usr/local/bin/npx \
    && ln -sf "$NODE_BIN/yarn"   /usr/local/bin/yarn \
    && ln -sf "$NODE_BIN/claude" /usr/local/bin/claude \
    # Give kibana full ownership of its home (covers NVM and .ssh)
    && chown -R kibana:kibana /home/kibana

RUN npm install -g js-yaml

# Make NVM available in all shell types:
#   /etc/profile.d  — login shells (ssh -l, su -, interactive login)
#   /etc/bash.bashrc — non-login interactive shells
#   /etc/environment — sets NVM_DIR for PAM-based sessions (non-interactive SSH)
RUN printf 'export NVM_DIR=/home/kibana/.nvm\n[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"\n' \
      > /etc/profile.d/nvm.sh \
    && printf '\nexport NVM_DIR=/home/kibana/.nvm\n[ -s "$NVM_DIR/nvm.sh" ] && . "$NVM_DIR/nvm.sh"\n' \
      >> /etc/bash.bashrc \
    && echo 'NVM_DIR=/home/kibana/.nvm' >> /etc/environment

COPY id_ed25519.pub /home/kibana/.ssh/authorized_keys
RUN chmod 600 /home/kibana/.ssh/authorized_keys \
    && chown kibana:kibana /home/kibana/.ssh/authorized_keys

# SSH setup
RUN mkdir -p /var/run/sshd

RUN sed -i \
    -e 's/#PermitRootLogin.*/PermitRootLogin no/' \
    -e 's/PermitRootLogin yes/PermitRootLogin no/' \
    -e 's/#PasswordAuthentication yes/PasswordAuthentication no/' \
    -e 's/PasswordAuthentication yes/PasswordAuthentication no/' \
    -e 's/#PubkeyAuthentication.*/PubkeyAuthentication yes/' \
    /etc/ssh/sshd_config

RUN ssh-keygen -A

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 22

ENTRYPOINT ["/entrypoint.sh"]
