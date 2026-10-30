"""
Django settings for USHIKA (WhatsApp Cloud API integration).

Every deploy-specific value comes from environment variables. In development
they are loaded from `.env` (see `.env.example`).
"""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


DEBUG = env_bool("DJANGO_DEBUG", False)

SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set when DJANGO_DEBUG is false.")
    SECRET_KEY = "django-insecure-dev-only-key"

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")
CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "rest_framework.authtoken",
    "django_filters",
    "drf_spectacular",
    "whatsapp",
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

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# SQLite for the POC; set DB_ENGINE=postgres (and install requirements-prod.txt) for production.
if os.getenv("DB_ENGINE", "sqlite").strip().lower() == "postgres":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", "ushika"),
            "USER": os.getenv("POSTGRES_USER", "ushika"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", ""),
            "HOST": os.getenv("POSTGRES_HOST", "localhost"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": int(os.getenv("POSTGRES_CONN_MAX_AGE", "60")),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = os.getenv("TIME_ZONE", "UTC")
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Downloaded WhatsApp media lives here. There is deliberately no public MEDIA_URL
# route: files are only served through the authenticated attachment download and preview API.
MEDIA_ROOT = Path(os.getenv("MEDIA_ROOT", BASE_DIR / "storage"))

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.TokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.SearchFilter",
        "rest_framework.filters.OrderingFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "whatsapp.api.pagination.StandardPagination",
    "PAGE_SIZE": 50,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "USHIKA WhatsApp API",
    "DESCRIPTION": "Internal REST API for WhatsApp messages, contacts, attachments and delivery statuses.",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # Docs are open while developing; in production only staff can read them.
    "SERVE_PERMISSIONS": (
        ["rest_framework.permissions.AllowAny"] if DEBUG else ["rest_framework.permissions.IsAdminUser"]
    ),
}

# All WhatsApp/Meta configuration lives in this one dict. Code reads it at call
# time (never at import time) so tests can override it with override_settings.
WHATSAPP = {
    "ACCESS_TOKEN": os.getenv("WHATSAPP_ACCESS_TOKEN", ""),
    "PHONE_NUMBER_ID": os.getenv("WHATSAPP_PHONE_NUMBER_ID", ""),
    "BUSINESS_ACCOUNT_ID": os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", ""),
    "APP_SECRET": os.getenv("WHATSAPP_APP_SECRET", ""),
    "VERIFY_TOKEN": os.getenv("WHATSAPP_VERIFY_TOKEN", ""),
    "API_VERSION": os.getenv("WHATSAPP_API_VERSION") or "v25.0",
    "GRAPH_BASE_URL": os.getenv("WHATSAPP_GRAPH_BASE_URL", "https://graph.facebook.com"),
    "REQUEST_TIMEOUT": float(os.getenv("WHATSAPP_REQUEST_TIMEOUT", "20")),
    # Off: media is saved on request through the API. On: saved on arrival when the contact's level allows it.
    "DOWNLOAD_MEDIA": env_bool("WHATSAPP_DOWNLOAD_MEDIA", False),
    "MEDIA_TYPES": env_list("WHATSAPP_MEDIA_TYPES", "image,document,audio,video,sticker"),
    "MEDIA_MAX_BYTES": int(os.getenv("WHATSAPP_MEDIA_MAX_BYTES", str(100 * 1024 * 1024))),
    "MEDIA_MAX_ATTEMPTS": int(os.getenv("WHATSAPP_MEDIA_MAX_ATTEMPTS", "5")),
}

# Background work (media downloads). Off: runs inline right after the webhook's
# DB commit. On: queued to Celery workers via Redis.
USE_CELERY = env_bool("USE_CELERY", False)
CELERY_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ACKS_LATE = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {"format": "%(asctime)s %(levelname)s %(name)s: %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "standard"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        # Replaces Django's default handlers, which would otherwise print every request warning twice.
        "django": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "whatsapp": {
            "handlers": ["console"],
            "level": os.getenv("WHATSAPP_LOG_LEVEL", "INFO"),
            "propagate": False,
        },
    },
}

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", True)
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = int(os.getenv("DJANGO_SECURE_HSTS_SECONDS", "3600"))
    SECURE_HSTS_INCLUDE_SUBDOMAINS = env_bool("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
    SECURE_HSTS_PRELOAD = env_bool("DJANGO_SECURE_HSTS_PRELOAD", False)
