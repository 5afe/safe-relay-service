#!/bin/sh

set -euo pipefail

celery -A safe_relay_service.taskapp worker -l INFO
