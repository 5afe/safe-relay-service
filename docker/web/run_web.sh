#!/bin/bash

set -euo pipefail

echo "==> Migrating Django models ... "
python manage.py migrate --noinput
python manage.py setup_gas_station
python manage.py setup_safe_relay
if [ "${DEPLOY_MASTER_COPY_ON_INIT:-0}" = 1 ]; then
    python manage.py deploy_safe_master_copy
fi

echo "==> Collecting statics ... "
DOCKER_SHARED_DIR=/nginx
rm -rf $DOCKER_SHARED_DIR/*
STATIC_ROOT=$DOCKER_SHARED_DIR/staticfiles python manage.py collectstatic --noinput

echo "==> Running Server ... "
/usr/local/bin/python manage.py runserver 0.0.0.0:27017 &
sleep infinity