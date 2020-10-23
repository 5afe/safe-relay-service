#!/bin/bash

DOCKER_SHARED_DIR=/nginx

set -euo pipefail

echo "==> Migrating Django models..."
python manage.py migrate --noinput

echo "==> Setup Gas Station..."
python manage.py setup_gas_station

echo "==> $(date +%H:%M:%S) ==> Setting up service... "
python manage.py setup_service

echo "==> Collecting statics ... "
rm -rf $DOCKER_SHARED_DIR/*
STATIC_ROOT=$DOCKER_SHARED_DIR/staticfiles python manage.py collectstatic --noinput

echo "==> Running Gunicorn ... "
gunicorn --pythonpath "$PWD" config.wsgi:application --log-file=- --error-logfile=- --access-logfile=- --log-level info --logger-class='safe_relay_service.relay.utils.CustomGunicornLogger' -b unix:$DOCKER_SHARED_DIR/gunicorn.socket -b 0.0.0.0:8888 --worker-class gevent
