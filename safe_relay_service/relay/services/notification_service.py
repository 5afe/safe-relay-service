import json
from logging import getLogger
from typing import Dict, List, Optional
from urllib.parse import urljoin

import requests

logger = getLogger(__name__)


class NotificationServiceProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            from django.conf import settings

            notification_service_uri = settings.NOTIFICATION_SERVICE_URI
            if notification_service_uri:
                cls.instance = NotificationService(
                    settings.NOTIFICATION_SERVICE_URI,
                    settings.NOTIFICATION_SERVICE_PASS,
                )
            else:
                logger.warning(
                    "Using mock NotificationService because no NOTIFICATION_SERVICE_URI was configured"
                )
                cls.instance = NotificationServiceMock(None, None)
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class NotificationService:
    def __init__(self, base_uri: str, password: str, headers: Optional[Dict] = None):
        self.base_uri = base_uri
        self.notification_endpoint_uri = urljoin(
            base_uri, "/api/v1/simple-notifications/"
        )
        self.notification_pass = password
        self.password = password
        self.headers = headers if headers else {"X-Forwarded-Proto": "https"}

    def send_notification(self, message: Dict, owners: List[str]) -> bool:
        if not owners:
            return False
        else:
            data = {
                "message": json.dumps(message),
                "devices": owners,
                "password": self.password,
            }
            r = requests.post(
                self.notification_endpoint_uri, json=data, headers=self.headers
            )
            return r.ok

    def send_create_notification(self, safe_address: str, owners: List[str]) -> bool:
        message = {
            "type": "safeCreation",
            "safe": safe_address,
            "owners": ",".join(owners),  # Firebase just allows strings
        }
        return self.send_notification(message, owners)


class NotificationServiceMock(NotificationService):
    def send_notification(self, owners: List[str], message: Dict) -> bool:
        return True
