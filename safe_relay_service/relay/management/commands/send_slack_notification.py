from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand

from gnosis.eth import EthereumClientProvider
from gnosis.eth.ethereum_client import EthereumNetworkName

from ....version import __version__
from ...services import SlackNotificationClientProvider


class Command(BaseCommand):
    help = 'Send slack notification'
    ethereum_client = EthereumClientProvider()
    slack_notification_client = SlackNotificationClientProvider()

    def handle(self, *args, **options):
        app_name = apps.get_app_config('relay').verbose_name
        startup_message = str.format("Starting {} version {} on {}",
                                     app_name, __version__,
                                     self.ethereum_client.get_network_name().name.capitalize())

        self.stdout.write(self.style.SUCCESS(startup_message))
        if settings.SLACK_API_WEBHOOK:
            try:
                self.slack_notification_client.send(startup_message)
            except Exception:
                self.stdout.write(self.style.ERROR("Cannot send slack notification for API webhook=%s",
                                                   settings.SLACK_API_WEBHOOK, exc_info=True))
