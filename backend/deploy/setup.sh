#!/usr/bin/env bash
# Sets up the web server, or updates it, from an unpacked backend bundle.
#
#   sudo bash setup.sh <unpacked backend dir> <snapshot s3 uri> <allowed hosts>
#
# Run as root on the instance by scripts/deploy.sh (SSM Run Command) on every
# deploy. Idempotent: a fresh Ubuntu 24.04 box gets packages, user, swap,
# virtualenv and services; a running one gets the new code, dependencies and
# settings, then gunicorn restarts.
#
# Layout (the systemd units in deploy/systemd/ assume it):
#   /opt/data-jockey/backend   the code, plus data/ (the snapshot) and db.sqlite3,
#                              which are kept across deploys
#   /opt/data-jockey/venv      virtualenv
#   /etc/data-jockey/env       settings; the secret key is generated once and kept
set -euo pipefail

if [ $# -ne 3 ]; then
  sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
fi
SRC=$1
SNAPSHOT_S3_URI=$2
ALLOWED_HOSTS=$3

APP_USER=data-jockey
APP_DIR=/opt/data-jockey
CODE_DIR=$APP_DIR/backend
VENV=$APP_DIR/venv
ENV_DIR=/etc/data-jockey
ENV_FILE=$ENV_DIR/env

# One setup at a time (a deploy retried while the last one is still running).
exec 9>/var/lock/data-jockey-setup.lock
flock 9

export DEBIAN_FRONTEND=noninteractive

echo "== Packages"
if [ ! -f /etc/apt/sources.list.d/caddy-stable.list ]; then
  # Caddy's own apt repo (https://caddyserver.com/docs/install#debian-ubuntu-raspbian);
  # Ubuntu's caddy package is well behind.
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
    | gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
    > /etc/apt/sources.list.d/caddy-stable.list
  chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg /etc/apt/sources.list.d/caddy-stable.list
fi
missing=()
for package in caddy python3-venv rsync; do
  if ! dpkg -s "$package" >/dev/null 2>&1; then
    missing+=("$package")
  fi
done
if [ ${#missing[@]} -gt 0 ]; then
  apt-get update -q
  apt-get install -y -q "${missing[@]}"
fi

echo "== Swap"
# 1 GB of RAM: pip installs and two gunicorn workers are happier with swap.
if [ ! -f /swapfile ]; then
  fallocate -l 1G /swapfile
  chmod 600 /swapfile
  mkswap /swapfile
  echo "/swapfile none swap sw 0 0" >> /etc/fstab
fi
swapon --show=NAME --noheadings | grep -qx /swapfile || swapon /swapfile

echo "== User"
if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home-dir "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
fi

echo "== Code"
mkdir -p "$CODE_DIR/data"
# --delete removes files dropped from the repo; the excludes are runtime state
# (and so are never deleted): the snapshot, Django's own database, bytecode.
rsync -a --delete \
  --exclude /data/ \
  --exclude /db.sqlite3 \
  --exclude /staticfiles/ \
  --exclude /.env \
  --exclude __pycache__/ \
  "$SRC"/ "$CODE_DIR"/
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "== Virtualenv"
if [ ! -x "$VENV/bin/python" ]; then
  sudo -u "$APP_USER" python3 -m venv "$VENV"
fi
sudo -u "$APP_USER" "$VENV/bin/pip" install --quiet --upgrade pip
sudo -u "$APP_USER" "$VENV/bin/pip" install --quiet -r "$CODE_DIR/requirements.txt"

echo "== Settings"
mkdir -p "$ENV_DIR"
secret_key=""
if [ -f "$ENV_FILE" ]; then
  secret_key=$(sed -n 's/^DJANGO_SECRET_KEY=//p' "$ENV_FILE")
fi
if [ -z "$secret_key" ]; then
  # URL-safe characters only, so nothing in it needs quoting in an EnvironmentFile.
  secret_key=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
fi
# Written whole every deploy, so a setting changed here reaches the server.
cat > "$ENV_FILE.tmp" <<EOF
# Written by backend/deploy/setup.sh on every deploy; edits here are overwritten.
DJANGO_SECRET_KEY=$secret_key
DJANGO_ALLOWED_HOSTS=$ALLOWED_HOSTS
DATA_JOCKEY_SNAPSHOT_S3_URI=$SNAPSHOT_S3_URI
# Caddy is the one proxy in front of gunicorn (the API's per-IP rate limit).
DJANGO_NUM_PROXIES=1
EOF
chown root:"$APP_USER" "$ENV_FILE.tmp"
chmod 640 "$ENV_FILE.tmp"
mv "$ENV_FILE.tmp" "$ENV_FILE"

echo "== Django"
# Only the default database (sessions, admin); the router keeps migrations off the snapshot.
sudo -u "$APP_USER" sh -c "set -a; . '$ENV_FILE'; cd '$CODE_DIR'; '$VENV/bin/python' manage.py migrate --noinput"
sudo -u "$APP_USER" sh -c "set -a; . '$ENV_FILE'; cd '$CODE_DIR'; '$VENV/bin/python' manage.py collectstatic --noinput --clear"

echo "== Services"
cp "$CODE_DIR"/deploy/systemd/*.service "$CODE_DIR"/deploy/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
# Fetch now rather than wait for the timer, so a fresh box has data straight away.
systemctl start data-jockey-snapshot.service
systemctl enable --now data-jockey-snapshot.timer
systemctl enable data-jockey-web.service
systemctl restart data-jockey-web.service

cp "$CODE_DIR/deploy/Caddyfile" /etc/caddy/Caddyfile
caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
systemctl enable caddy
systemctl reload-or-restart caddy

echo "== Check"
# Through Caddy, as a visitor would come in (gunicorn may take a moment to start).
for attempt in $(seq 1 10); do
  status=$(curl -s -o /dev/null -w '%{http_code}' -H "Host: ${ALLOWED_HOSTS%%,*}" http://127.0.0.1/api/v1/snapshot/ || true)
  if [ "$status" = "200" ]; then
    echo "GET /api/v1/snapshot/ -> 200"
    exit 0
  fi
  sleep 2
done
echo "GET /api/v1/snapshot/ -> $status (expected 200)" >&2
journalctl -u data-jockey-web.service -n 30 --no-pager >&2
exit 1
