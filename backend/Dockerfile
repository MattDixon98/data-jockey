# syntax=docker/dockerfile:1
# The Django site (both APIs) under gunicorn: the `web` and `snapshot` services in
# compose.yaml. Caddy (deploy/caddy/) sits in front and serves the static files
# collected here.
#
#   docker compose build web                (from backend/)
#   docker compose run --rm web python manage.py test api
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
  PYTHONUNBUFFERED=1 \
  PIP_NO_CACHE_DIR=1 \
  PIP_DISABLE_PIP_VERSION_CHECK=1

# uid 1000 matches the usual first user on a Linux host, so a bind-mounted data/
# (compose.override.yaml) stays writable for both.
ARG APP_UID=1000
RUN useradd --uid "$APP_UID" --create-home app

WORKDIR /app

# Dependencies in their own layer: a code change doesn't reinstall them.
COPY requirements.txt .
RUN pip install -r requirements.txt

# The code stays root-owned (read-only to the app); only data/ (the snapshot) and
# var/ (Django's own database) are writable, and both are volumes at runtime.
COPY . .
# collectstatic needs settings to load; DEBUG only so it skips the secret key check.
RUN DJANGO_DEBUG=true python manage.py collectstatic --noinput \
  && mkdir -p data var \
  && chown app:app data var

USER app
ENV DJANGO_DB_PATH=/app/var/db.sqlite3
EXPOSE 8000

# migrate touches only the default database (the router keeps it off the snapshot).
# exec: gunicorn becomes PID 1, so `docker stop` reaches it and it shuts down cleanly.
CMD ["sh", "-c", "python manage.py migrate --noinput && exec gunicorn project.wsgi:application --bind 0.0.0.0:8000 --workers 2 --access-logfile -"]
