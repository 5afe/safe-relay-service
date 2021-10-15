from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from django_celery_beat.models import PeriodicTask

from .factories import SafeFundingFactory


class TestCommands(TestCase):
    def test_check_safes(self):
        buf = StringIO()
        call_command("check_safes", stdout=buf)
        self.assertIn("All safes are deployed", buf.getvalue())

        safe_funding = SafeFundingFactory(safe_deployed=False)
        call_command("check_safes", stdout=buf)
        self.assertIn(
            "Safe=%s Status=%s" % (safe_funding.safe_id, safe_funding.status()),
            buf.getvalue(),
        )

    def test_deploy_pending_safes(self):
        buf = StringIO()
        call_command("deploy_pending_safes", stdout=buf)
        self.assertIn("All safes are deployed", buf.getvalue())

    def test_deploy_safe_contracts(self):
        buf = StringIO()
        call_command("deploy_safe_contracts", stdout=buf)
        self.assertEqual(buf.getvalue().count("Contract has been deployed on"), 3)

    def test_send_slack_notification(self):
        buf = StringIO()
        call_command("send_slack_notification", stdout=buf)
        text = buf.getvalue()
        self.assertIn("Slack not configured, ignoring", text)
        self.assertIn("Starting Safe Relay Service version", text)

    def test_setup_service(self):
        from ..management.commands.setup_service import Command

        number_tasks = len(Command.tasks)
        self.assertEqual(PeriodicTask.objects.all().count(), 0)
        call_command("setup_service")
        self.assertEqual(PeriodicTask.objects.all().count(), number_tasks)
