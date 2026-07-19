# Build stage
FROM docker.io/library/node:24-alpine AS build
WORKDIR /app
# App version baked into the bundle (Vite define reads process.env at build).
# Sourced from the compose build arg (APP_VERSION → VITE_APP_VERSION).
ARG VITE_APP_VERSION=dev
ENV VITE_APP_VERSION=${VITE_APP_VERSION}
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
