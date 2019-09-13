from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from django_celery_beat.models import PeriodicTask

from .factories import (SafeContractFactory, SafeCreation2Factory,
                        SafeFundingFactory)


class TestCommands(TestCase):
    def test_check_safes(self):
        buf = StringIO()
        call_command('check_safes', stdout=buf)
        self.assertIn('All safes are deployed', buf.getvalue())

        safe_funding = SafeFundingFactory(safe_deployed=False)
        call_command('check_safes', stdout=buf)
        self.assertIn('Safe=%s Status=%s' % (safe_funding.safe_id, safe_funding.status()),
                      buf.getvalue())

    def test_deploy_pending_safes(self):
        buf = StringIO()
        call_command('deploy_pending_safes', stdout=buf)
        self.assertIn('All safes are deployed', buf.getvalue())

    def test_deploy_safe_contracts(self):
        buf = StringIO()
        call_command('deploy_safe_contracts', stdout=buf)
        self.assertEqual(buf.getvalue().count('Contract has been deployed on'), 3)

    def test_setup_internal_txs(self):
        buf = StringIO()

        safe = SafeContractFactory()
        call_command('setup_internal_txs', stdout=buf)
        self.assertIn('Generated 0 SafeTxStatus', buf.getvalue())

        SafeCreation2Factory(safe=safe, block_number=10)
        call_command('setup_internal_txs', stdout=buf)
        self.assertIn('Generated 1 SafeTxStatus', buf.getvalue())

    def test_setup_safe_relay(self):
        from ..management.commands.setup_safe_relay import Command
        number_tasks = len(Command.tasks)
        self.assertEqual(PeriodicTask.objects.all().count(), 0)
        call_command('setup_safe_relay')
        self.assertEqual(PeriodicTask.objects.all().count(), number_tasks)
