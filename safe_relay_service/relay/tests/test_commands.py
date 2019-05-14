from django.core.management import call_command
from django.test import TestCase


# TODO Test ALL the commands
class TestCommands(TestCase):
    def test_setup_safe_relay(self):
        call_command('setup_safe_relay')
