from .base import *
from .base import env

# GENERAL

SECRET_KEY = env("DJANGO_SECRET_KEY")

ALLOWED_HOSTS = [
    "relayer-service",
    env("HOST_RELAYER", default="localhost"),
    env("DJANGO_ALLOWED_HOSTS", default="circles.garden"),
]

# DATABASES

DATABASES["default"]["ATOMIC_REQUESTS"] = False

# SECURITY

SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_SSL_REDIRECT = env.bool("DJANGO_SECURE_SSL_REDIRECT", default=False)
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = True
CSRF_COOKIE_HTTPONLY = True
CSRF_TRUSTED_ORIGINS = env.list("SERVER_URI", default=[])
SECURE_HSTS_SECONDS = 60
SECURE_HSTS_INCLUDE_SUBDOMAINS = env.bool(
    "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", default=True
)
SECURE_HSTS_PRELOAD = env.bool("DJANGO_SECURE_HSTS_PRELOAD", default=True)
SECURE_CONTENT_TYPE_NOSNIFF = env.bool(
    "DJANGO_SECURE_CONTENT_TYPE_NOSNIFF", default=True
)
SECURE_BROWSER_XSS_FILTER = True
X_FRAME_OPTIONS = "DENY"

# TEMPLATES

TEMPLATES[0]["OPTIONS"]["loaders"] = [
    (
        "django.template.loaders.cached.Loader",
        [
            "django.template.loaders.filesystem.Loader",
            "django.template.loaders.app_directories.Loader",
        ],
    ),
]

# ADMIN

ADMIN_URL = env("DJANGO_ADMIN_URL", default=r"^admin/")

# GUNICORN

INSTALLED_APPS += ["gunicorn"]

# Django CORS

CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])

# SAFE

SAFE_FUNDING_CONFIRMATIONS = env.int("SAFE_FUNDING_CONFIRMATIONS", default=3)
FIXED_GAS_PRICE = env.int("FIXED_GAS_PRICE", default=1)
