#!/bin/bash

set -euo pipefail

echo "==> Migrating Django models ... "
python manage.py migrate --noinput
echo "setup gas station"
python manage.py setup_gas_station
echo "setup safe-relay"
python manage.py setup_safe_relay

if [ "${DEPLOY_MASTER_COPY_ON_INIT:-0}" = 1 ]; then
    echo "deploy master copy"
    python manage.py deploy_safe_master_copy
fi


if [ "${DEPLOY_SWAGGER:-0}" = 1 ]; then
    echo "==> Collecting statics ... "
    DOCKER_SHARED_DIR=/nginx
    rm -rf $DOCKER_SHARED_DIR/*
    STATIC_ROOT=$DOCKER_SHARED_DIR/staticfiles python manage.py collectstatic --noinput
fi

if [ "${DEBUG:-0}" = 1 ]; then
    echo "==> Running Server ... "
    /usr/local/bin/python manage.py runserver 0.0.0.0:27017 &
    sleep infinity
else
    echo "==> Running Gunicorn ... "
    gunicorn --pythonpath "$PWD" config.wsgi:application --log-file=- --error-logfile=- --access-logfile '-' --log-level info -b unix:$DOCKER_SHARED_DIR/gunicorn.socket -b 0.0.0.0:8888 --worker-class gevent
fi