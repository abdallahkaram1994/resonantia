# Build context is the repo root (see compose.yaml) so the frontend can be built in this image.
FROM node:24-slim AS frontend

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


FROM caddy:2-alpine

COPY caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=frontend /app/dist /srv
