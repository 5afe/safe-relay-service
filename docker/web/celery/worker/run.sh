#!/bin/bash

set -euo pipefail

# DEBUG set in .env
if [ ${DEBUG:-0} = 1 ]; then
    log_level="debug"
else
    log_level="info"
fi

sleep 5
echo "==> Running Celery worker <=="
exec celery -A safe_relay_service.taskapp worker --loglevel $log_level -c 4
