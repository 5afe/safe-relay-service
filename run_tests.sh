#!/bin/bash

set -euo pipefail

export DJANGO_SETTINGS_MODULE=config.settings.test
export DJANGO_DOT_ENV_FILE=.env.test
docker compose -f docker-compose.yml -f docker-compose.dev.yml build --force-rm db redis ganache
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --no-start db redis ganache
docker restart db redis ganache
sleep 3
python manage.py check
pytest
coverage run --source=safe_relay_service -m py.test -rxXs
coverage report
