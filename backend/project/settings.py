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
  "strawberry_django",
  "rest_framework",
  "django_filters",
  "drf_spectacular",
  "app",
  "racing",
  "api",
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

# Both APIs (api/graphql/, api/rest/): every paginated list is capped, so no
# request can pull a whole table.
API_PAGE_SIZE = 50
API_MAX_PAGE_SIZE = 200

STRAWBERRY_DJANGO = {
  "PAGINATION_DEFAULT_LIMIT": API_PAGE_SIZE,
  "PAGINATION_MAX_LIMIT": API_MAX_PAGE_SIZE,
  # Column descriptions are the racing models' help_text, as in the REST docs.
  "FIELD_DESCRIPTION_FROM_HELP_TEXT": True,
}

# The REST API (api/rest/): read-only and public, so no authentication (and no
# cookies, so no CSRF). Responses carry an ETag from the snapshot's built_at and
# may be cached this many seconds (api/rest/caching.py); fetch_snapshot checks
# for a new snapshot every 15 minutes.
API_CACHE_MAX_AGE = 300

# Per-IP rate limit on the REST API (DRF AnonRateThrottle). The counters live in
# Django's cache: none is configured, so the default per-process memory cache,
# which means each gunicorn worker counts separately (the real limit is this x
# the worker count). Fine for one small server; a shared cache would make it exact.
API_RATE_LIMIT = "60/min"
# How many proxies sit in front of Django. Behind Caddy every request comes from
# 127.0.0.1, so the client's IP has to be read from X-Forwarded-For (set this to 1
# on the server). 0 (local, no proxy) uses the connection's own address and
# ignores X-Forwarded-For, which a client could fake.
API_NUM_PROXIES = int(os.environ.get("DJANGO_NUM_PROXIES", "0"))

REST_FRAMEWORK = {
  "DEFAULT_AUTHENTICATION_CLASSES": [],
  "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.AllowAny"],
  "DEFAULT_RENDERER_CLASSES": [
    "rest_framework.renderers.JSONRenderer",
    "rest_framework.renderers.BrowsableAPIRenderer",
  ],
  "DEFAULT_PAGINATION_CLASS": "api.rest.pagination.Pagination",
  "DEFAULT_FILTER_BACKENDS": ["django_filters.rest_framework.DjangoFilterBackend"],
  "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
  "EXCEPTION_HANDLER": "api.rest.views.exception_handler",
  "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.AnonRateThrottle"],
  "DEFAULT_THROTTLE_RATES": {"anon": API_RATE_LIMIT},
  "NUM_PROXIES": API_NUM_PROXIES,
}

SPECTACULAR_SETTINGS = {
  "TITLE": "Data Jockey API",
  "DESCRIPTION": (
    "UK/IRE horse racing: racecards, results, prices at each crawl, our own fair win odds and "
    "the undervalued flags, and the model's track record. Read-only; the data is rebuilt once a day. "
    "The same data is available as GraphQL at /graphql/. "
    f"Rate limited per IP address ({API_RATE_LIMIT}): over that, 429 Too Many Requests with a "
    "Retry-After header."
  ),
  "VERSION": "1",
  "SERVE_INCLUDE_SCHEMA": False,
  "SCHEMA_PATH_PREFIX": "/api/v1",
}

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
