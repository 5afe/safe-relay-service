#!/bin/bash

set -euo pipefail

celery -A config.celery_app worker -l INFO
