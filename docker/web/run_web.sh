#!/bin/bash

set -euo pipefail


echo "==> $(date +%H:%M:%S) ==> Migrating Django models... "
python manage.py migrate --noinput
echo "==> $(date +%H:%M:%S) ==> Setup Gas Station..."
python manage.py setup_gas_station
echo "==> $(date +%H:%M:%S) ==> Setting up service... "
python manage.py setup_service

echo "==> $(date +%H:%M:%S) ==> Collecting statics... "
DOCKER_SHARED_DIR=/nginx
rm -rf $DOCKER_SHARED_DIR/*
# STATIC_ROOT=$DOCKER_SHARED_DIR/staticfiles python manage.py collectstatic --noinput &
cp -r staticfiles/ $DOCKER_SHARED_DIR/

echo "==> $(date +%H:%M:%S) ==> Send via Slack info about service version and network"
python manage.py send_slack_notification &

if [ "${DEPLOY_MASTER_COPY_ON_INIT:-0}" = 1 ]; then
  echo "==> $(date +%H:%M:%S) ==> Deploy Safe master copy..."
  python manage.py deploy_safe_contracts
fi

echo "==> $(date +%H:%M:%S) ==> Running Gunicorn... "
exec gunicorn --worker-class gevent --pythonpath "$PWD" config.wsgi:application --timeout 60 --graceful-timeout 60 --log-file=- --error-logfile=- --access-logfile=- --log-level info --logger-class='safe_relay_service.relay.utils.CustomGunicornLogger' -b unix:$DOCKER_SHARED_DIR/gunicorn.socket -b 0.0.0.0:8888
