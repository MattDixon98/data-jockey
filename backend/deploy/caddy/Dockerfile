# syntax=docker/dockerfile:1
# Caddy with everything it serves baked in: the React app (built here from
# ../frontend) and Django's collected static files (copied from the web image).
# Built by compose.yaml, which supplies the two named contexts:
#   frontend  ../frontend
#   web       the web service's image
#
# The Node stage runs on the build machine's own platform: its output is plain
# files, so a linux/arm64 image doesn't need Node emulated.
FROM --platform=$BUILDPLATFORM node:22-alpine AS site
WORKDIR /src
COPY --from=frontend package.json package-lock.json ./
RUN npm ci
# Named files, not the whole directory: a host node_modules (wrong platform) must never get in.
COPY --from=frontend index.html tsconfig.json vite.config.ts ./
COPY --from=frontend src ./src
RUN npm run build

FROM caddy:2
COPY deploy/caddy/Caddyfile /etc/caddy/Caddyfile
COPY --from=site /src/dist /srv/site
COPY --from=web /app/staticfiles /srv/static
