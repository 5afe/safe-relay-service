#!/bin/bash
DJANGO_SETTINGS_MODULE=config.settings.test_rinkeby DJANGO_DOT_ENV_FILE=.env_rinkeby pytest safe_relay_service/relay/tests/test_views.py
