# Static frontend for the Azure LLM Serving Demo, served as an Azure App Service (Linux
# container) via nginx. Build from the repository root so the build context matches
# `backend/Dockerfile`'s convention, e.g.:
#   docker build -f frontend/Dockerfile -t llmserving-frontend:latest \
#     --build-arg VITE_API_BASE_URL=https://<backend-app>.azurewebsites.net .
#
# Vite bakes VITE_* env vars into the compiled JS at build time (not runtime), so the backend's
# URL must be supplied as a build ARG matching the actual backend App Service hostname for this
# environment — it can't be changed later without rebuilding the image.
FROM node:20-slim AS build

ARG VITE_API_BASE_URL=""
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

WORKDIR /app
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npx tsc --noEmit && npx vite build

FROM nginx:1.27-alpine AS runtime

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD wget -qO- http://127.0.0.1:80/ || exit 1
