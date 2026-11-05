# Build from the repository root. Set BACKEND_URL at runtime for the same-origin
# signed-token proxy; cloud images do not need an environment-specific Vite build.
FROM node:20-slim AS build

ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npx tsc --noEmit && npx vite build

FROM nginx:1.27-alpine AS runtime

ENV BACKEND_URL=http://127.0.0.1:8000
ENV NGINX_ENVSUBST_FILTER=^BACKEND_URL$
COPY frontend/nginx.conf /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:80/ || exit 1
