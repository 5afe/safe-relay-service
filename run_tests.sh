#!/bin/bash

set -euo pipefail

docker-compose -f docker-compose.yml -f docker-compose.dev.yml build --force-rm db redis ganache
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up --no-start db redis ganache
docker restart safe-relay-service_db_1 safe-relay-service_redis_1 safe-relay-service_ganache_1
sleep 2
DJANGO_SETTINGS_MODULE=config.settings.test DJANGO_DOT_ENV_FILE=.env.local python manage.py check
DJANGO_SETTINGS_MODULE=config.settings.test DJANGO_DOT_ENV_FILE=.env.local pytest
