import logging
from typing import Any, Dict, Tuple

from ethereum.transactions import secpk1n
from ethereum.utils import checksum_encode
from hexbytes import HexBytes
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from safe_relay_service.ether.signing import EthereumSignedMessage
from safe_relay_service.safe.models import SafeCreation, SafeFunding

from .ethereum_service import EthereumServiceProvider
from .safe_service import SafeServiceProvider

logger = logging.getLogger(__name__)


def isoformat_without_ms(date_time):
    return date_time.replace(microsecond=0).isoformat()


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
            elif int(data, 16) == 0:
                raise ValidationError("0x0 address is not allowed")
            elif int(data, 16) == 1:
                raise ValidationError("0x1 address is not allowed")
        except ValueError:
            raise ValidationError("Address %s is not checksumed" % data)
        except Exception:
            raise ValidationError("Address %s is not valid" % data)

        return data


class HexadecimalField(serializers.Field):
    def to_representation(self, obj):
        if not obj:
            return '0x'
        else:
            return obj.hex()

    def to_internal_value(self, data):
        if not data or data == '0x':
            return None
        try:
            return HexBytes(data)
        except ValueError:
            raise ValidationError("%s is not hexadecimal" % data)


# ================================================ #
#                Base Serializers
# ================================================ #
class SignatureSerializer(serializers.Serializer):
    v = serializers.IntegerField(min_value=0, max_value=30)
    r = serializers.IntegerField(min_value=1, max_value=secpk1n)
    s = serializers.IntegerField(min_value=1, max_value=secpk1n)


class SignatureResponseSerializer(serializers.Serializer):
    """
    Use CharField because of JavaScript problems with big integers
    """
    v = serializers.CharField()
    r = serializers.CharField()
    s = serializers.CharField()


class TransactionSerializer(serializers.Serializer):
    from_ = EthereumAddressField()
    value = serializers.IntegerField(min_value=0)
    data = serializers.CharField()
    gas = serializers.CharField()
    gas_price = serializers.CharField()
    nonce = serializers.IntegerField(min_value=0)

    def get_fields(self):
        result = super().get_fields()
        # Rename `from_` to `from`
        from_ = result.pop('from_')
        result['from'] = from_
        return result


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


class SafeCreationSerializer(serializers.Serializer):
    s = serializers.IntegerField(min_value=1, max_value=secpk1n - 1)
    owners = serializers.ListField(child=EthereumAddressField(), min_length=1)
    threshold = serializers.IntegerField(min_value=1)

    def validate(self, data):
        super().validate(data)
        owners = data['owners']
        threshold = data['threshold']

        if threshold > len(owners):
            raise ValidationError("Threshold cannot be greater than number of owners")

        return data


class SafeTransactionCreationResponseSerializer(serializers.Serializer):
    signature = SignatureResponseSerializer()
    tx = TransactionSerializer()
    payment = serializers.CharField()
    safe = EthereumAddressField()


class SafeFundingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SafeFunding
        fields = ('safe_funded', 'deployer_funded', 'deployer_funded_tx_hash', 'safe_deployed', 'safe_deployed_tx_hash')


class SafeMultisigEstimateTxSerializer(serializers.Serializer):
    safe = EthereumAddressField()
    to = EthereumAddressField(default=None, allow_null=True)
    value = serializers.IntegerField(min_value=0)
    data = HexadecimalField(default=None, allow_null=True)
    operation = serializers.IntegerField(min_value=0, max_value=2)  # Call, DelegateCall or Create

    def validate(self, data):
        super().validate(data)

        if not data['to'] and not data['data']:
            raise ValidationError('`data` and `to` cannot both be null')

        if data['operation'] == 2:
            if data['to']:
                raise ValidationError('Operation is Create, but `to` was provided')
        elif not data['to']:
            raise ValidationError('Operation is not create, but `to` was not provided')

        return data


class SafeMultisigTxSerializer(SafeMultisigEstimateTxSerializer):
    safe_tx_gas = serializers.IntegerField(min_value=0)
    data_gas = serializers.IntegerField(min_value=0)
    gas_price = serializers.IntegerField(min_value=0)
    gas_token = EthereumAddressField(default=None, allow_null=True)
    nonce = serializers.IntegerField(min_value=0)
    signatures = serializers.ListField(child=SignatureSerializer())

    def validate(self, data):
        super().validate(data)

        safe_creation = SafeCreation.objects.select_related('safe').get(safe=data['safe'])

        signatures = data['signatures']

        if len(signatures) < safe_creation.threshold:
            raise ValidationError('Need at least %d signatures' % safe_creation.threshold)

        safe_service = SafeServiceProvider()
        # TODO check this - if safe_creation.safe.has_valid_master_copy():
        if safe_creation.safe.address in safe_service.valid_master_copy_addresses:
            raise ValidationError('Safe proxy master-copy={} not valid')

        if not data['to'] and not data['data']:
            raise ValidationError('`data` and `to` cannot both be null')

        if data['operation'] == 2:
            if data['to']:
                raise ValidationError('Operation is Create, but `to` was provided')
            elif not data['data']:
                raise ValidationError('Operation is Create, but not `data` was provided')
        elif not data['to']:
            raise ValidationError('Operation is not create, but `to` was not provided')

        if data['gas_token'] == 2:
            raise ValidationError('Gas Token is still not supported')

        tx_hash = safe_service.get_hash_for_safe_tx(data['safe'], data['to'], data['value'], data['data'],
                                                    data['operation'], data['safe_tx_gas'], data['data_gas'],
                                                    data['gas_price'], data['gas_token'], data['nonce'])

        owners = [EthereumServiceProvider().get_signing_address(tx_hash,
                                                                signature['v'],
                                                                signature['r'],
                                                                signature['s']) for signature in signatures]

        for owner in owners:
            if owner not in safe_creation.owners:
                raise ValidationError('Owner=%s is not a member of the safe' % owner)

        signature_pairs = [(s['v'], s['r'], s['s']) for s in signatures]
        if not safe_service.check_hash(tx_hash, safe_service.signatures_to_bytes(signature_pairs), owners):
            raise ValidationError('Signatures are not sorted by owner')

        data['owners'] = owners
        return data
