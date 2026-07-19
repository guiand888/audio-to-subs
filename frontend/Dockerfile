# Build stage
FROM docker.io/library/node:24-alpine AS build
WORKDIR /app
# The app version is NOT baked into the bundle. The UI resolves it at runtime
# from the backend's GET /api/version (which is itself derived from the
# repo-root VERSION file), so no build arg is needed here.
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Serve stage
# Unprivileged image: runs as UID 101 and writes temp/pid to writable
# locations, so it works under rootless Podman without starting as root.
FROM quay.io/nginx/nginx-unprivileged:1.30-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
