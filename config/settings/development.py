from .base import *
from .base import env

# GENERAL

DEBUG = True
SECRET_KEY = env("DJANGO_SECRET_KEY")

ALLOWED_HOSTS = [
    "relayer-service",
    env("HOST_RELAYER", default="localhost"),
]

# DJANGO DEBUG TOOLBAR

INSTALLED_APPS += ["debug_toolbar"]

MIDDLEWARE += [
    "debug_toolbar.middleware.DebugToolbarMiddleware",
    "debug_toolbar_force.middleware.ForceDebugToolbarMiddleware",
]

DEBUG_TOOLBAR_CONFIG = {
    "DISABLE_PANELS": [
        "debug_toolbar.panels.redirects.RedirectsPanel",
    ],
    "SHOW_TEMPLATE_CONTEXT": True,
}

# CELERY

CELERY_ALWAYS_EAGER = False

# Django CORS

CORS_ORIGIN_ALLOW_ALL = True

# SAFE

FIXED_GAS_PRICE = 1
SAFE_FUNDING_CONFIRMATIONS = 0
