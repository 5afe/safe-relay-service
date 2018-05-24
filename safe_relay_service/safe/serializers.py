import json
import logging
from datetime import datetime
from typing import Any, Dict, Tuple

from django.conf import settings
from django.db.models import Q
from django.utils import timezone
from ethereum.utils import checksum_encode
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from safe_relay_service.ether.signing import EthereumSignedMessage
from safe_relay_service.safe.models import Device, DevicePair
from safe_relay_service.safe.tasks import send_notification

from .helpers import validate_google_billing_purchase

logger = logging.getLogger(__name__)


def isoformat_without_ms(date_time):
    return date_time.replace(microsecond=0).isoformat()


# ================================================ #
#                Base Serializers
# ================================================ #


class SignatureSerializer(serializers.Serializer):
    v = serializers.IntegerField(min_value=0, max_value=30)
    r = serializers.IntegerField(min_value=0)
    s = serializers.IntegerField(min_value=0)


# ================================================ #
#                Custom Fields
# ================================================ #
class EthereumAddressField(serializers.Field):
    """
    Ethereum address checksumed
    https://github.com/ethereum/EIPs/blob/master/EIPS/eip-55.md
    """

    def to_representation(self, obj):
        return obj

    def to_internal_value(self, data):
        # Check if address is valid

        try:
            if checksum_encode(data) != data:
                raise ValueError
        except ValueError:
            raise ValidationError("Address %s is not checksumed" % data)
        except Exception:
            raise ValidationError("Address %s is not valid" % data)

        return data


# ================================================ #
#                 Serializers
# ================================================ #
class SignedMessageSerializer(serializers.Serializer):
    """
    Inherit from this class and define get_hashed_fields function
    Take care not to define `message`, `message_hash` or `signing_address` fields
    """
    signature = SignatureSerializer()

    def validate(self, data):
        super().validate(data)
        v = data['signature']['v']
        r = data['signature']['r']
        s = data['signature']['s']
        message = ''.join(self.get_hashed_fields(data))
        ethereum_signed_message = EthereumSignedMessage(message, v, r, s)
        data['message'] = message
        data['message_hash'] = ethereum_signed_message.message_hash
        data['signing_address'] = ethereum_signed_message.get_signing_address()
        return data

    def get_hashed_fields(self, data: Dict[str, Any]) -> Tuple[str]:
        """
        :return: fields to concatenate for hash calculation
        :rtype: Tuple[str]
        """
        return ()
