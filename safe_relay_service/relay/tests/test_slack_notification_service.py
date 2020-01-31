from django.test import TestCase

from ..services import SlackNotificationClient, SlackNotificationClientProvider
from ..services.slack_notification_client import EmptyClient


class TestSlackClient(TestCase):
    def test_configuration(self):
        # Create instance with no args, it should raise exception when executing client.send()
        client = SlackNotificationClient()
        self.assertRaises(Exception, client.send, 'some text')

    def test_provider(self):
        with self.settings(SLACK_API_WEBHOOK=None):
            client = SlackNotificationClientProvider()
            self.assertIsInstance(client, EmptyClient)

        SlackNotificationClientProvider.del_singleton()
