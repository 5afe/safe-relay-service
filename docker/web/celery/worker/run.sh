#!/bin/bash

set -euo pipefail

exec celery -A safe_relay_service.taskapp worker -l INFO
