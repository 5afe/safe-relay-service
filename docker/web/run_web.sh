#!/bin/bash

set -euo pipefail

echo "==> Migrating Django models..."
python manage.py migrate --noinput
echo "==> Setup Gas Station..."
python manage.py setup_gas_station
echo "==> Setup Safe Relay Task..."
python manage.py setup_safe_relay
if [ "${DEPLOY_MASTER_COPY_ON_INIT:-0}" = 1 ]; then
    echo "==> Deploy Safe master copy..."
    python manage.py deploy_safe_contracts
fi

echo "==> Collecting statics ... "
DOCKER_SHARED_DIR=/nginx
rm -rf $DOCKER_SHARED_DIR/*
STATIC_ROOT=$DOCKER_SHARED_DIR/staticfiles python manage.py collectstatic --noinput

echo "==> Running Gunicorn ... "
exec gunicorn --pythonpath "$PWD" config.wsgi:application --log-file=- --error-logfile=- --access-logfile=- --log-level info --logger-class='safe_relay_service.relay.utils.CustomGunicornLogger' -b unix:$DOCKER_SHARED_DIR/gunicorn.socket -b 127.0.0.1:8888 --worker-class gevent
