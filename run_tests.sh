#!/bin/bash

set -euo pipefail

docker-compose build --force-rm
docker-compose up --no-start db redis ganache
docker restart safe-relay-service_db_1 safe-relay-service_redis_1 safe-relay-service_ganache_1
sleep 2
DJANGO_DOT_ENV_FILE=.env_local python3 -m pytest
