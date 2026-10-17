FROM node:20-slim
WORKDIR /app
COPY package.json ./
COPY src ./src
COPY schema ./schema
COPY scripts/register-tunnel.sh ./scripts/register-tunnel.sh
COPY entrypoint.sh ./entrypoint.sh
RUN chmod +x ./entrypoint.sh ./scripts/register-tunnel.sh \
 && apt-get update && apt-get install -y --no-install-recommends ca-certificates curl python3 && rm -rf /var/lib/apt/lists/* \
 && mkdir -p /data && chown node:node /data
USER node
EXPOSE 8080
ENTRYPOINT ["/app/entrypoint.sh"]
