import environ
import socket

ROOT_DIR = (
    environ.Path(__file__) - 3
)  # (safe_relay_service/config/settings/base.py - 3 = safe-relay-service/)
APPS_DIR = ROOT_DIR.path("safe_relay_service")

env = environ.Env()

READ_DOT_ENV_FILE = env.bool("DJANGO_READ_DOT_ENV_FILE", default=False)
DOT_ENV_FILE = env("DJANGO_DOT_ENV_FILE", default=None)
if READ_DOT_ENV_FILE or DOT_ENV_FILE:
    DOT_ENV_FILE = DOT_ENV_FILE or ".env"
    # OS environment variables take precedence over variables from .env
    env.read_env(str(ROOT_DIR.path(DOT_ENV_FILE)))

# GENERAL

DEBUG = env.bool("DEBUG", False)
TIME_ZONE = "UTC"
LANGUAGE_CODE = "en-us"
SITE_ID = 1
USE_I18N = True
USE_L10N = True
USE_TZ = True

# DATABASES

psql_url = (
    "psql://"
    + env("POSTGRES_USER")
    + ":"
    + env("POSTGRES_PASSWORD")
    + "@"
    + env("POSTGRES_HOST")
    + ":"
    + env("POSTGRES_PORT")
    + "/"
    + env("POSTGRES_DATABASE_RELAYER")
)

DATABASES = {
    "default": env.db("RELAYER_DATABASE", default=psql_url),
}

DATABASES["default"]["ATOMIC_REQUESTS"] = True

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# URLS

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

# APPS

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.sessions",
    "django.contrib.sites",
    "django.contrib.staticfiles",
    "corsheaders",
]

THIRD_PARTY_APPS = [
    "rest_framework",
    "rest_framework.authtoken",
    "drf_yasg",
]

LOCAL_APPS = [
    "safe_relay_service.relay.apps.RelayConfig",
    "safe_relay_service.tokens.apps.TokensConfig",
    "safe_relay_service.gas_station.apps.GasStationConfig",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# MIDDLEWARE

MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

# STATIC

STATIC_ROOT = "/usr/share/nginx/html/relayer"

STATIC_URL = "/static/"

STATICFILES_DIRS = [
    str(APPS_DIR.path("static")),
]

STATICFILES_FINDERS = [
    "django.contrib.staticfiles.finders.FileSystemFinder",
    "django.contrib.staticfiles.finders.AppDirectoriesFinder",
]

# MEDIA

MEDIA_ROOT = str(APPS_DIR("media"))
MEDIA_URL = "/media/"

# TEMPLATES

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [
            str(APPS_DIR.path("templates")),
        ],
        "OPTIONS": {
            "debug": DEBUG,
            "loaders": [
                "django.template.loaders.filesystem.Loader",
                "django.template.loaders.app_directories.Loader",
            ],
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.template.context_processors.i18n",
                "django.template.context_processors.media",
                "django.template.context_processors.static",
                "django.template.context_processors.tz",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# FIXTURES

FIXTURE_DIRS = (str(APPS_DIR.path("fixtures")),)

# EMAIL

EMAIL_BACKEND = "django.core.mail.backends.dummy.EmailBackend"

# ADMIN

ADMIN_URL = r"^admin/"

ADMINS = [
    ("""Circles""", "webmaster@joincircles.net"),
]

MANAGERS = ADMINS

# Celery

INSTALLED_APPS += [
    "django_celery_beat",
]

CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="django://")
CELERY_RESULT_BACKEND = CELERY_BROKER_URL
CELERY_ACCEPT_CONTENT = ["json"]
CELERY_RESULT_SERIALIZER = "json"
CELERY_TASK_SERIALIZER = "json"

# Django REST Framework

REST_FRAMEWORK = {
    "PAGE_SIZE": 10,
    "DEFAULT_PAGINATION_CLASS": "rest_framework.pagination.LimitOffsetPagination",
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.AllowAny",),
    "DEFAULT_RENDERER_CLASSES": (
        "djangorestframework_camel_case.render.CamelCaseJSONRenderer",
    ),
    "DEFAULT_PARSER_CLASSES": (
        "djangorestframework_camel_case.parser.CamelCaseJSONParser",
    ),
    "DEFAULT_VERSIONING_CLASS": "rest_framework.versioning.NamespaceVersioning",
    "EXCEPTION_HANDLER": "safe_relay_service.relay.views.custom_exception_handler",
}

# LOGGING

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "require_debug_false": {"()": "django.utils.log.RequireDebugFalse"},
        "ignore_check_url": {"()": "safe_relay_service.relay.utils.IgnoreCheckUrl"},
        "ignore_succeeded_none": {
            "()": "safe_relay_service.utils.celery.IgnoreSucceededNone"
        },
    },
    "formatters": {
        "verbose": {
            "format": "%(asctime)s [%(levelname)s] [%(processName)s] %(message)s",
        },
        "celery_verbose": {
            "class": "safe_relay_service.utils.celery.PatchedCeleryFormatter",
            "format": "%(asctime)s [%(levelname)s] [%(task_id)s/%(task_name)s] %(message)s",
            # 'format': '%(asctime)s [%(levelname)s] [%(processName)s] [%(task_id)s/%(task_name)s] %(message)s'
        },
    },
    "handlers": {
        "mail_admins": {
            "level": "ERROR",
            "filters": ["require_debug_false"],
            "class": "django.utils.log.AdminEmailHandler",
        },
        "console": {
            "level": "DEBUG",
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
        "celery_console": {
            "level": "DEBUG",
            "filters": ["ignore_succeeded_none"],
            "class": "logging.StreamHandler",
            "formatter": "celery_verbose",
        },
    },
    "loggers": {
        "": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
        },
        "celery.worker.strategy": {
            "handlers": ["console"],
            "level": "DEBUG" if DEBUG else "INFO",
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": True,
        },
        "django.security.DisallowedHost": {
            "level": "ERROR",
            "handlers": ["console"],
            "propagate": True,
        },
        "django.server": {  # Gunicorn uses `gunicorn.access`
            "level": "INFO",
            "handlers": ["console"],
            "propagate": True,
            "filters": ["ignore_check_url"],
        },
    },
}

REDIS_URL = env("RELAYER_REDIS_URL", default="redis://redis:6379/0")

# ETHEREUM

ETH_HASH_PREFIX = env("ETH_HASH_PREFIX", default="ETH")
ETHEREUM_NODE_URL = env("ETHEREUM_NODE_ENDPOINT", default=None)
ETHEREUM_TRACING_NODE_URL = env("ETHEREUM_TRACING_NODE_URL", default=ETHEREUM_NODE_URL)

GAS_STATION_NUMBER_BLOCKS = env("GAS_STATION_NUMBER_BLOCKS", default=300)

# SAFE

SAFE_FUNDER_PRIVATE_KEY = env("SAFE_FUNDER_PRIVATE_KEY", default=None)

# Maximum ether (no wei) for a single transaction (security limit)

SAFE_FUNDER_MAX_ETH = env.int("SAFE_FUNDER_MAX_ETH", default=0.1)
SAFE_FUNDING_CONFIRMATIONS = env.int(
    "SAFE_FUNDING_CONFIRMATIONS", default=3
)  # Set to at least 3

# Master Copy Address of Safe Contract
# SAFE_ADDRESS => SAFE CONTRACT V1.3.0
SAFE_CONTRACT_ADDRESS = env("SAFE_ADDRESS", default="0x" + "0" * 39 + "1")

# SAFE_ADDRESS_CRC => SAFE CONTRACT CIRCLES
SAFE_V1_1_1_CONTRACT_ADDRESS = env(
    "SAFE_CONTRACT_ADDRESS_CRC", default="0x" + "0" * 39 + "2"
)
SAFE_V1_0_0_CONTRACT_ADDRESS = env(
    "SAFE_CONTRACT_ADDRESS_CRC", default="0x" + "0" * 39 + "2"
)
SAFE_V0_0_1_CONTRACT_ADDRESS = env(
    "SAFE_CONTRACT_ADDRESS_CRC)", default="0x" + "0" * 39 + "2"
)
SAFE_VALID_CONTRACT_ADDRESSES = set(
    env.list(
        "SAFE_VALID_CONTRACT_ADDRESSES",
        default=[
            "0x" + "0" * 39 + "1",
            "0x" + "0" * 39 + "2",
        ],
    )
    + [
        SAFE_CONTRACT_ADDRESS,
        SAFE_V1_1_1_CONTRACT_ADDRESS,
        SAFE_V1_0_0_CONTRACT_ADDRESS,
        SAFE_V0_0_1_CONTRACT_ADDRESS,
    ]
)

# PROXY_FACTORY_ADDRESS => PROXY FACTORY V1.3.0
SAFE_PROXY_FACTORY_ADDRESS = env("PROXY_FACTORY_ADDRESS", default="0x" + "0" * 39 + "3")

# PROXY_FACTORY_ADDRESS_CRC => PROXY FACTORY CIRCLES VERSION
SAFE_PROXY_FACTORY_V1_0_0_ADDRESS = env(
    "PROXY_FACTORY_ADDRESS_CRC", default="0x" + "0" * 39 + "4"
)
SAFE_DEFAULT_CALLBACK_HANDLER = env(
    "SAFE_DEFAULT_CALLBACK_HANDLER", default="0x" + "0" * 39 + "5"
)

# If FIXED_GAS_PRICE is None, GasStation will be used
FIXED_GAS_PRICE = env.int("FIXED_GAS_PRICE", default=None)
SAFE_TX_SENDER_PRIVATE_KEY = env("SAFE_TX_SENDER_PRIVATE_KEY", default=None)

SAFE_CHECK_DEPLOYER_FUNDED_DELAY = env.int(
    "SAFE_CHECK_DEPLOYER_FUNDED_DELAY", default=1 * 30
)
SAFE_CHECK_DEPLOYER_FUNDED_RETRIES = env.int(
    "SAFE_CHECK_DEPLOYER_FUNDED_RETRIES", default=10
)
SAFE_FIXED_CREATION_COST = env.int("SAFE_FIXED_CREATION_COST", default=None)
SAFE_ACCOUNTS_BALANCE_WARNING = env.int(
    "SAFE_ACCOUNTS_BALANCE_WARNING", default=200000000000000000
)  # 0.2 Eth
SAFE_TX_NOT_MINED_ALERT_MINUTES = env("SAFE_TX_NOT_MINED_ALERT_MINUTES", default=10)

NOTIFICATION_SERVICE_URI = env("NOTIFICATION_SERVICE_URI", default=None)
NOTIFICATION_SERVICE_PASS = env("NOTIFICATION_SERVICE_PASS", default=None)

TOKEN_LOGO_BASE_URI = env("TOKEN_LOGO_BASE_URI", default="")
TOKEN_LOGO_EXTENSION = env("TOKEN_LOGO_EXTENSION", default=".png")

# CACHES

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("RELAYER_REDIS_URL"),
        "OPTIONS": {
            "CLIENT_CLASS": "django_redis.client.DefaultClient",
            "IGNORE_EXCEPTIONS": True,
        },
    }
}

# CIRCLES

CIRCLES_HUB_ADDRESS = env("HUB_ADDRESS", default="0x" + "0" * 39 + "6")
GRAPH_NODE_ENDPOINT = env("GRAPH_NODE_ENDPOINT", default="")
MIN_TRUST_CONNECTIONS = env("MIN_TRUST_CONNECTIONS", default=3)
SUBGRAPH_NAME = env("SUBGRAPH_NAME", default="")

# DOCKER

hostname, _, ips = socket.gethostbyname_ex(socket.gethostname())
INTERNAL_IPS = ["127.0.0.1", "10.0.2.2"]
INTERNAL_IPS += [ip[:-1] + "1" for ip in ips]
