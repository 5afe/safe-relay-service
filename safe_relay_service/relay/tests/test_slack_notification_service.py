from django.test import TestCase

from ..services.slack_notification_client import (EmptyClient, MockClient)
from ..services import (SlackNotificationClientProvider,  SlackNotificationClient)


class TestSlackClient(TestCase):

    def test_provider(self):
        with self.settings(NOTIFICATIONS=None):
            client = SlackNotificationClientProvider()
            self.assertIsInstance(client, EmptyClient)

        SlackNotificationClientProvider.del_singleton()

        with self.settings(NOTIFICATIONS={'class':
                'safe_relay_service.relay.services.slack_notification_client.MockClient'}):
            client = SlackNotificationClientProvider()
            self.assertIsInstance(client, MockClient)

