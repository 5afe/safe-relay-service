from django.apps import AppConfig
from django.conf import settings
from logging import getLogger

from gnosis.eth import EthereumClientProvider

from ..version import __version__

logger = getLogger(__name__)


class RelayConfig(AppConfig):
    name = 'safe_relay_service.relay'

    def ready(self):
        from .services import SlackNotificationClientProvider
        ethereum_client = EthereumClientProvider()

        slack_notification_client = SlackNotificationClientProvider()
        startup_message = str.format("Starting {} version {} on {}",
                        self.verbose_name, __version__,
                        ethereum_client.get_network_name().name.capitalize())
        logger.info(startup_message)
        if settings.SLACK_API_WEBHOOK:
            try:
                slack_notification_client.send(startup_message)
            except Exception:
                logger.error("Cannot send slack notification for API webhook=%s",
                             settings.SLACK_API_WEBHOOK, exc_info=True)
