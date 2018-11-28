import json
from urllib.parse import urljoin
from typing import Dict, Union, List
import requests
from logging import getLogger


logger = getLogger(__name__)


class NotificationServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            notification_service_uri = settings.NOTIFICATION_SERVICE_URI
            if notification_service_uri:
                cls.instance = NotificationService(settings.NOTIFICATION_SERVICE_URI)
            else:
                logger.warning('Using mock NotificationService because no NOTIFICATION_SERVICE_URI was configured')
                cls.instance = NotificationServiceMock(None)
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class NotificationService:
    def __init__(self, base_uri: str, headers: Union[Dict, None]=None):
        self.uri = base_uri
        self.notification_uri = urljoin(base_uri, '/api/v1/simple-notifications/')
        self.headers = headers if headers else {'X-Forwarded-Proto': 'https'}

    def send_notification(self, message: Dict, owners: List[str]) -> bool:
        if not owners:
            return False
        else:
            data = {
                'message': json.dumps(message),
                'devices': owners,
            }
            r = requests.post(self.notification_uri, json=data, headers=self.headers)
            return r.ok

    def send_create_notification(self, safe_address: str, owners: List[str]) -> bool:
        message = {
            "type": "safeCreation",
            "safe": safe_address,
        }
        return self.send_notification(message, owners)


class NotificationServiceMock(NotificationService):
    def send_notification(self, owners: List[str], message: Dict) -> bool:
        return True
