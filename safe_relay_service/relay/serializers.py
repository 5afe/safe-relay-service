import logging
from typing import Union

from django_eth.constants import (NULL_ADDRESS, SIGNATURE_S_MAX_VALUE,
                                  SIGNATURE_S_MIN_VALUE)
from django_eth.serializers import (EthereumAddressField, Sha3HashField,
                                    TransactionResponseSerializer)
from gnosis.safe.ethereum_service import EthereumServiceProvider
from gnosis.safe.safe_service import SafeServiceProvider
from gnosis.safe.serializers import (SafeMultisigEstimateTxSerializer,
                                     SafeMultisigTxSerializer,
                                     SafeSignatureSerializer)
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from safe_relay_service.relay.models import SafeCreation, SafeFunding
from safe_relay_service.tokens.models import Token

logger = logging.getLogger(__name__)


# TODO Refactor
def validate_gas_token(address: Union[str, None]) -> str:
    """
    Raises ValidationError if gas token is not valid
    :param address: Gas Token address
    :return: address if everything goes well
    """
    if address and address != NULL_ADDRESS:
        try:
            token_db = Token.objects.get(address=address)
            if not token_db.gas:
                raise ValidationError('Token %s - %s cannot be used as gas token' % (token_db.name, address))
        except Token.DoesNotExist:
            raise ValidationError('Token %s not found' % address)
    return address


class SafeCreationSerializer(serializers.Serializer):
    s = serializers.IntegerField(min_value=SIGNATURE_S_MIN_VALUE,
                                 max_value=SIGNATURE_S_MAX_VALUE)
    owners = serializers.ListField(child=EthereumAddressField(), min_length=1)
    threshold = serializers.IntegerField(min_value=1)
    payment_token = EthereumAddressField(default=None, allow_null=True, allow_zero_address=True)

    def validate_payment_token(self, value):
        return validate_gas_token(value)

    def validate(self, data):
        super().validate(data)
        owners = data['owners']
        threshold = data['threshold']

        if threshold > len(owners):
            raise ValidationError("Threshold cannot be greater than number of owners")

        return data


class SafeRelayMultisigEstimateTxSerializer(SafeMultisigEstimateTxSerializer):
    def validate_gas_token(self, value):
        return validate_gas_token(value)

    def validate(self, data):
        super().validate(data)
        return data


# TODO Rename this
class SafeRelayMultisigTxSerializer(SafeMultisigTxSerializer):
    signatures = serializers.ListField(child=SafeSignatureSerializer())

    def validate(self, data):
        super().validate(data)

        safe_address = data['safe']
        safe_creation = SafeCreation.objects.select_related('safe').get(safe=safe_address)

        signatures = data['signatures']

        if len(signatures) < safe_creation.threshold:
            raise ValidationError('Need at least %d signatures' % safe_creation.threshold)

        safe_service = SafeServiceProvider()

        refund_receiver = data.get('refund_receiver')
        if refund_receiver and refund_receiver != NULL_ADDRESS:
            raise ValidationError('Refund Receiver is not configurable')

        tx_hash = safe_service.get_hash_for_safe_tx(safe_address, data['to'], data['value'], data['data'],
                                                    data['operation'], data['safe_tx_gas'], data['data_gas'],
                                                    data['gas_price'], data['gas_token'], data['refund_receiver'],
                                                    data['nonce'])

        owners = [EthereumServiceProvider().get_signing_address(tx_hash,
                                                                signature['v'],
                                                                signature['r'],
                                                                signature['s']) for signature in signatures]

        signature_pairs = [(s['v'], s['r'], s['s']) for s in signatures]
        if not safe_service.check_hash(tx_hash, safe_service.signatures_to_bytes(signature_pairs), owners):
            raise ValidationError('Signatures are not sorted by owner: %s' % owners)

        data['owners'] = owners
        return data


# ================================================ #
#                Responses                         #
# ================================================ #
class SignatureResponseSerializer(serializers.Serializer):
    """
    Use CharField because of JavaScript problems with big integers
    """
    v = serializers.CharField()
    r = serializers.CharField()
    s = serializers.CharField()


class SafeResponseSerializer(serializers.Serializer):
    address = EthereumAddressField()
    master_copy = EthereumAddressField()
    nonce = serializers.IntegerField(min_value=0)
    threshold = serializers.IntegerField(min_value=1)
    owners = serializers.ListField(child=EthereumAddressField(), min_length=1)


class SafeTransactionCreationResponseSerializer(serializers.Serializer):
    signature = SignatureResponseSerializer()
    tx = TransactionResponseSerializer()
    payment = serializers.CharField()
    payment_token = EthereumAddressField(allow_null=True, allow_zero_address=True)
    safe = EthereumAddressField()
    deployer = EthereumAddressField()
    funder = EthereumAddressField()


class SafeFundingResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = SafeFunding
        fields = ('safe_funded', 'deployer_funded', 'deployer_funded_tx_hash', 'safe_deployed', 'safe_deployed_tx_hash')


class SafeMultisigTxResponseSerializer(serializers.Serializer):
    transaction_hash = Sha3HashField()


class SafeMultisigEstimateTxResponseSerializer(serializers.Serializer):
    safe_tx_gas = serializers.IntegerField(min_value=0)
    data_gas = serializers.IntegerField(min_value=0)
    operational_gas = serializers.IntegerField(min_value=0)
    gas_price = serializers.IntegerField(min_value=0)
    last_used_nonce = serializers.IntegerField(min_value=0, allow_null=True)
    gas_token = EthereumAddressField(allow_null=True, allow_zero_address=True)
