from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand

import requests
from requests import RequestException

from gnosis.eth import EthereumClientProvider

from ....version import __version__


class Command(BaseCommand):
    help = "Send slack notification"

    def handle(self, *args, **options):
        ethereum_client = EthereumClientProvider()
        app_name = apps.get_app_config("relay").verbose_name
        network_name = ethereum_client.get_network().name.capitalize()
        startup_message = f"Starting {app_name} version {__version__} on {network_name}"
        self.stdout.write(self.style.SUCCESS(startup_message))

        if settings.SLACK_API_WEBHOOK:
            try:
                r = requests.post(
                    settings.SLACK_API_WEBHOOK, json={"text": startup_message}
                )
                if r.ok:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f'Slack configured, "{startup_message}" sent'
                        )
                    )
                else:
                    raise RequestException()
            except RequestException:
                self.stdout.write(self.style.ERROR("Cannot send slack notification"))
        else:
            self.stdout.write(self.style.SUCCESS("Slack not configured, ignoring"))
