#!/bin/bash

set -euo pipefail

# DEBUG set in .env_docker_compose
if [ ${DEBUG:-0} = 1 ]; then
    log_level="debug"
else
    log_level="info"
fi

echo "==> $(date +%H:%M:%S) ==> Migrating Django models... "
python manage.py migrate --noinput

echo "==> $(date +%H:%M:%S) ==> Running Celery worker <=="
exec celery -A safe_relay_service.taskapp worker --loglevel $log_level -c 4
