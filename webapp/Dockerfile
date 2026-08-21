# Stage 1 — build Angular
FROM node:20-slim AS ng-build
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm install --legacy-peer-deps
COPY frontend/ ./
RUN npm run build -- --configuration production

# Stage 2 — runtime
FROM node:20-slim
WORKDIR /app
COPY backend/package*.json ./
RUN npm install --omit=dev
COPY backend/src ./src
COPY --from=ng-build /build/frontend/dist/frontend/browser ./public
COPY entrypoint.sh ./scripts/entrypoint.sh
COPY scripts/register-tunnel.sh ./scripts/register-tunnel.sh
RUN chmod +x ./scripts/entrypoint.sh ./scripts/register-tunnel.sh
EXPOSE 5000
ENTRYPOINT ["/app/scripts/entrypoint.sh"]
