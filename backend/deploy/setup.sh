#!/usr/bin/env bash
# Sets up the web server, or updates it: Docker, then the site's containers.
#
#   sudo bash setup.sh <bundle dir> <snapshot s3 uri> <allowed hosts> <site domain> <registry> <image tag>
#
# Run as root on the instance by scripts/deploy.sh (SSM Run Command) on every
# deploy. The bundle holds compose.yaml and this script; the images (web, caddy)
# are pulled from ECR (<registry>/data-jockey-web:<image tag>...), pushed there by
# scripts/push_images.sh. Idempotent: a fresh Ubuntu 24.04 box gets Docker, swap
# and the containers; a running one gets the new images and settings.
#
# Layout:
#   /opt/data-jockey/compose.yaml   the stack (backend/compose.yaml)
#   /opt/data-jockey/.env           compose's own settings: images, tag, domain
#   /etc/data-jockey/env            Django's settings; the secret key is generated once and kept
#   Docker volumes                  data-jockey_snapshot (the SQLite file), _django-db
#                                   (admin users, sessions), _caddy-data (certificates)
set -euo pipefail

if [ $# -ne 6 ]; then
  sed -n '2,18p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
fi
SRC=$1
SNAPSHOT_S3_URI=$2
ALLOWED_HOSTS=$3
SITE_DOMAIN=$4
REGISTRY=$5
IMAGE_TAG=$6

APP_DIR=/opt/data-jockey
ENV_DIR=/etc/data-jockey
ENV_FILE=$ENV_DIR/env
PROJECT=data-jockey
REGION=eu-west-2
COMPOSE=(docker compose --project-directory "$APP_DIR" -f "$APP_DIR/compose.yaml")

# One setup at a time (a deploy retried while the last one is still running).
exec 9>/var/lock/data-jockey-setup.lock
flock 9

export DEBIAN_FRONTEND=noninteractive

echo "== Docker"
if ! command -v docker >/dev/null 2>&1; then
  # Docker's own apt repo (https://docs.docker.com/engine/install/ubuntu/); Ubuntu's
  # docker.io has no compose plugin.
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  codename=$(. /etc/os-release && echo "$VERSION_CODENAME")
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc]" \
    "https://download.docker.com/linux/ubuntu $codename stable" > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
# Container logs are capped (the default json-file log grows without limit on a 10 GB disk).
daemon_json='{"log-driver": "json-file", "log-opts": {"max-size": "10m", "max-file": "3"}}'
if [ "$(cat /etc/docker/daemon.json 2>/dev/null)" != "$daemon_json" ]; then
  echo "$daemon_json" > /etc/docker/daemon.json
  systemctl restart docker
fi
systemctl enable --now docker

echo "== Swap"
# 1 GB of RAM: Docker plus two gunicorn workers are happier with swap.
if [ ! -f /swapfile ]; then
  fallocate -l 1G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi
swapon --show=NAME --noheadings | grep -qx /swapfile || swapon /swapfile

echo "== Settings"
mkdir -p "$ENV_DIR" "$APP_DIR"
secret_key=""
if [ -f "$ENV_FILE" ]; then
  secret_key=$(sed -n 's/^DJANGO_SECRET_KEY=//p' "$ENV_FILE")
fi
if [ -z "$secret_key" ]; then
  # URL-safe characters only, so nothing in it needs quoting in an env file.
  secret_key=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
fi
# Written whole every deploy, so a setting changed here reaches the server.
# DJANGO_NUM_PROXIES and the snapshot path are set in compose.yaml.
cat > "$ENV_FILE.tmp" <<EOF
# Written by backend/deploy/setup.sh on every deploy; edits here are overwritten.
DJANGO_SECRET_KEY=$secret_key
DJANGO_ALLOWED_HOSTS=$ALLOWED_HOSTS
DATA_JOCKEY_SNAPSHOT_S3_URI=$SNAPSHOT_S3_URI
EOF
chmod 600 "$ENV_FILE.tmp"
mv "$ENV_FILE.tmp" "$ENV_FILE"

cp "$SRC/compose.yaml" "$APP_DIR/compose.yaml"
cat > "$APP_DIR/.env" <<EOF
# Written by backend/deploy/setup.sh on every deploy: which images run, and the domain.
IMAGE_REGISTRY=$REGISTRY/
IMAGE_TAG=$IMAGE_TAG
SITE_DOMAIN=$SITE_DOMAIN
EOF

echo "== Images ($IMAGE_TAG)"
# The AWS CLI snap (installed by scripts/deploy.sh's command) uses the instance role.
/snap/bin/aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"
"${COMPOSE[@]}" pull --quiet

echo "== Retiring the pre-Docker setup (if it's here)"
# Until 24 Nov the site ran from a venv under systemd behind a host Caddy. Their state
# moves into the volumes (the admin users' database, the current snapshot, so the site has
# data straight away); then the old services, Caddy package, user and files go.
old_code=$APP_DIR/backend
if [ -d "$old_code" ]; then
  for unit in data-jockey-web.service data-jockey-snapshot.timer data-jockey-snapshot.service caddy.service; do
    systemctl disable --now "$unit" 2>/dev/null || true
  done
  rm -f /etc/systemd/system/data-jockey-web.service /etc/systemd/system/data-jockey-snapshot.*
  systemctl daemon-reload
  # Creates the volumes (labelled as the project's) without starting anything.
  "${COMPOSE[@]}" create --no-build
  volume_dir() {
    docker volume inspect --format '{{ .Mountpoint }}' "${PROJECT}_$1"
  }
  if [ -f "$old_code/db.sqlite3" ] && [ ! -f "$(volume_dir django-db)/db.sqlite3" ]; then
    cp "$old_code/db.sqlite3" "$(volume_dir django-db)/"
  fi
  if [ -f "$old_code/data/data_jockey.sqlite3" ] && [ ! -f "$(volume_dir snapshot)/data_jockey.sqlite3" ]; then
    cp "$old_code"/data/data_jockey.sqlite3* "$(volume_dir snapshot)/"
  fi
  # The image's app user (uid 1000) owns its data.
  chown -R 1000:1000 "$(volume_dir django-db)" "$(volume_dir snapshot)"
  if dpkg -s caddy >/dev/null 2>&1; then
    apt-get purge -y -q caddy
    rm -f /etc/apt/sources.list.d/caddy-stable.list /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  fi
  rm -rf "$old_code" "$APP_DIR/venv"
  if id data-jockey >/dev/null 2>&1; then
    userdel data-jockey
  fi
fi

echo "== Snapshot"
# Fetch now rather than wait for the snapshot container's loop, so a fresh box has data
# before the check below (one HEAD request when it's already up to date).
"${COMPOSE[@]}" run --rm --no-deps snapshot python manage.py fetch_snapshot

echo "== Containers"
# --no-build: the server only runs pulled images. Unchanged containers are left running.
"${COMPOSE[@]}" up -d --no-build --remove-orphans
# Old images (earlier tags) would fill the disk over time.
docker image prune -af --filter "until=24h" >/dev/null

echo "== Check"
# Straight to gunicorn (it may take a moment to start): Caddy only answers HTTPS for the
# domain, and its certificate needs DNS pointing here, which a fresh box's new IP may not
# have yet. scripts/deploy.sh checks the public HTTPS URL afterwards.
status=000
for attempt in $(seq 1 15); do
  status=$(curl -s -o /dev/null -w '%{http_code}' -H "Host: ${ALLOWED_HOSTS%%,*}" http://127.0.0.1:8000/api/v1/snapshot/ || true)
  if [ "$status" = "200" ]; then
    echo "GET /api/v1/snapshot/ -> 200"
    "${COMPOSE[@]}" ps --format 'table {{.Service}}\t{{.Image}}\t{{.Status}}'
    exit 0
  fi
  sleep 2
done
echo "GET /api/v1/snapshot/ -> $status (expected 200)" >&2
"${COMPOSE[@]}" ps >&2
"${COMPOSE[@]}" logs --tail 30 web >&2
exit 1
