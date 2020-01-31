from abc import ABC, abstractmethod
from logging import getLogger
from typing import NoReturn, Optional
from urllib.parse import urljoin

from requests import post

logger = getLogger(__name__)


class NotificationClient(ABC):
    """
    Abstract base class for clients.
    """

    @abstractmethod
    def send(self, *args, **kwargs) -> NoReturn: pass


class SlackNotificationClientProvider:
    """
    Provides singletone handling of Notification clients.
    """

    def __new__(cls):
        """
        Returns the instance of EmptyClient if no settings are configurated
        """
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            if hasattr(settings, 'SLACK_API_WEBHOOK') and settings.SLACK_API_WEBHOOK:
                # Create instance
                cls.instance = SlackNotificationClient(webhook=settings.SLACK_API_WEBHOOK)
            else:
                logger.debug('Slack Notification system is disabled because no configuration was set')
                cls.instance = EmptyClient()
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class SlackNotificationClient(NotificationClient):
    """
    Client class that handles notifications on Slack.
    """

    def __init__(self, token: Optional[str] = None, channel: Optional[str] = None, webhook: Optional[str] = None,
                 base_url: str = 'https://www.slack.com/api/'):
        self._base_url = base_url
        self._channel = channel
        self._token = token
        self._webhook = webhook

    def _get_url(self, api_method):
        """Joins the base Slack URL and an API method to form an absolute URL.

        Args:
            api_method (str): The Slack Web API method. e.g. 'chat.postMessage'

        Returns:
            The absolute API URL.
                e.g. 'https://www.slack.com/api/chat.postMessage'
        """
        return urljoin(self._base_url, api_method)

    def send(self, text: str) -> NoReturn:
        """
        Sends a notification to a Slack channel or webhook address provided in the __init__.
        :param text: The text to submit to Slack
        :raises AssertionError if response doesn't go through
        :return: NoReturn
        """
        # Get authentication headers
        auth_header = None
        # Construct request body
        body = {'channel': self._channel, 'text': text, 'token': self._token}

        # Get complete api_url
        if self._channel:
            api_url = self._get_url('chat.postMessage')
        elif self._webhook:
            api_url = self._webhook
        else:
            raise Exception('Either webhook or channel is needed in SlackNotificationClient')

        # Send POST request
        response = post(api_url, json=body, headers=auth_header)

        # When posting to a webhook the response contains the `text` property whose value can be 'ok'
        # When posting to chat.postMessage the response is in json format
        assert response.status_code == 200 and response.text == 'ok' or response.json().get("ok") is True


class EmptyClient(NotificationClient):
    """
    EmptyClient is instantiated and returned by NotificationClientProvider when no NOTIFICATIONS configuration is
    provided in settings.
    """

    def send(self, *args, **kwargs) -> NoReturn:
        pass


class MockClient(NotificationClient):
    """
    Mock Client intended to be used in tests
    """

    def __init__(self):
        self.notifications = []

    def send(self, text):
        self.notifications.append(text)
