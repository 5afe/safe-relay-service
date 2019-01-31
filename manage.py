#!/usr/bin/env python
import os
import sys
sys.path.append("pycharm-debug-py3k.egg")
if __name__ == '__main__':
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')

    try:
        from django.core.management import execute_from_command_line
        import pydevd
        if os.environ.get('RUN_MAIN') or os.environ.get('WERKZEUG_RUN_MAIN'):
            pydevd.settrace('host.docker.internal', port=12345, stdoutToServer=True, stderrToServer=True)
    except ImportError:
        # The above import may fail for some other reason. Ensure that the
        # issue is really that Django is missing to avoid masking other
        # exceptions on Python 2.
        try:
            import django  # noqa
        except ImportError:
            raise ImportError(
                "Couldn't import Django. Are you sure it's installed and "
                "available on your PYTHONPATH environment variable? Did you "
                "forget to activate a virtual environment?"
            )
        raise

    # This allows easy placement of apps within the interior
    # safe_relay_service directory.
    current_path = os.path.dirname(os.path.abspath(__file__))
    sys.path.append(os.path.join(current_path, 'safe_relay_service'))

    execute_from_command_line(sys.argv)
