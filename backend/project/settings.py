import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# Secrets and per-environment settings come from environment variables so nothing
# sensitive is committed. Locally they're read from backend/.env (git-ignored);
# see backend/.env.example. Real environment variables take precedence.
load_dotenv(BASE_DIR / ".env")

# Off unless explicitly turned on, so a forgotten setting fails safe in production.
debug_setting = os.environ.get("DJANGO_DEBUG", "false")
DEBUG = debug_setting.lower() == "true"

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
  if not DEBUG:
    raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is not true")
  # Local development only, so `runserver` works without generating a key.
  SECRET_KEY = "django-insecure-local-development-only"

# Comma-separated list, e.g. "localhost,127.0.0.1,data-jockey.example.com".
allowed_hosts_setting = os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
ALLOWED_HOSTS = [host.strip() for host in allowed_hosts_setting.split(",") if host.strip()]

# Only send session and CSRF cookies over HTTPS outside local development.
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG

INSTALLED_APPS = [
  "django.contrib.admin",
  "django.contrib.auth",
  "django.contrib.contenttypes",
  "django.contrib.sessions",
  "django.contrib.messages",
  "django.contrib.staticfiles",
  "app",
  "racing",
]

MIDDLEWARE = [
  "django.middleware.security.SecurityMiddleware",
  "django.contrib.sessions.middleware.SessionMiddleware",
  "django.middleware.common.CommonMiddleware",
  "django.middleware.csrf.CsrfViewMiddleware",
  "django.contrib.auth.middleware.AuthenticationMiddleware",
  "django.contrib.messages.middleware.MessageMiddleware",
  "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "project.urls"

TEMPLATES = [
  {
    "BACKEND": "django.template.backends.django.DjangoTemplates",
    "DIRS": [BASE_DIR / "app" / "templates"],
    "APP_DIRS": True,
    "OPTIONS": {
      "context_processors": [
        "django.template.context_processors.debug",
        "django.template.context_processors.request",
        "django.contrib.auth.context_processors.auth",
        "django.contrib.messages.context_processors.messages",
      ],
    },
  },
]

WSGI_APPLICATION = "project.wsgi.application"

# The serving snapshot: the clean tables (UK/IRE) as one SQLite file, rebuilt
# daily by the Glue job (glue/data_jockey/serving.py) and swapped in on the
# server by `manage.py fetch_snapshot` (an atomic rename, so no restart).
# A relative DATA_JOCKEY_SNAPSHOT is taken from backend/.
SNAPSHOT_PATH = BASE_DIR / os.environ.get("DATA_JOCKEY_SNAPSHOT", "data/data_jockey.sqlite3")
# Where fetch_snapshot downloads it from: s3://data-jockey-clean-<account>/serving/data_jockey.sqlite3
SNAPSHOT_S3_URI = os.environ.get("DATA_JOCKEY_SNAPSHOT_S3_URI", "")
# The snapshot layout the racing models are written for (serving.FORMAT_VERSION);
# fetch_snapshot won't swap in a file with any other.
SNAPSHOT_FORMAT_VERSION = 1
AWS_REGION = "eu-west-2"

DATABASES = {
  # Django's own tables (sessions, admin). Never the racing data.
  "default": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": BASE_DIR / "db.sqlite3",
  },
  # The racing app's models (racing.routers.SnapshotRouter). Opened read-only,
  # and a new connection per request (CONN_MAX_AGE=0): a connection holds on to
  # the file it opened, so each request sees whichever snapshot is in place.
  "snapshot": {
    "ENGINE": "django.db.backends.sqlite3",
    "NAME": f"file:{SNAPSHOT_PATH}?mode=ro",
    "CONN_MAX_AGE": 0,
  },
}
DATABASE_ROUTERS = ["racing.routers.SnapshotRouter"]

AUTH_PASSWORD_VALIDATORS = []

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
