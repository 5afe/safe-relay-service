import logging

from django_eth.constants import (NULL_ADDRESS, SIGNATURE_S_MAX_VALUE,
                                  SIGNATURE_S_MIN_VALUE)
from django_eth.serializers import (EthereumAddressField, HexadecimalField,
                                    Sha3HashField, SignatureSerializer,
                                    TransactionResponseSerializer)
from gnosis.safe.ethereum_service import EthereumServiceProvider
from gnosis.safe.safe_service import SafeServiceProvider
from gnosis.safe.serializers import SafeMultisigTxSerializer
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from safe_relay_service.relay.models import SafeCreation, SafeFunding

logger = logging.getLogger(__name__)


class SafeCreationSerializer(serializers.Serializer):
    s = serializers.IntegerField(min_value=SIGNATURE_S_MIN_VALUE,
                                 max_value=SIGNATURE_S_MAX_VALUE)
    owners = serializers.ListField(child=EthereumAddressField(), min_length=1)
    threshold = serializers.IntegerField(min_value=1)

    def validate(self, data):
        super().validate(data)
        owners = data['owners']
        threshold = data['threshold']

        if threshold > len(owners):
            raise ValidationError("Threshold cannot be greater than number of owners")

        return data


class SafeRelayMultisigTxSerializer(SafeMultisigTxSerializer):
    signatures = serializers.ListField(child=SignatureSerializer())

    def validate(self, data):
        super().validate(data)

        safe_address = data['safe']
        safe_creation = SafeCreation.objects.select_related('safe').get(safe=safe_address)

        signatures = data['signatures']

        if len(signatures) < safe_creation.threshold:
            raise ValidationError('Need at least %d signatures' % safe_creation.threshold)

        safe_service = SafeServiceProvider()

        gas_token = data.get('gas_token')
        if gas_token and gas_token != NULL_ADDRESS:
            raise ValidationError('Gas Token is still not supported')

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


class SafeTransactionCreationResponseSerializer(serializers.Serializer):
    signature = SignatureResponseSerializer()
    tx = TransactionResponseSerializer()
    payment = serializers.CharField()
    safe = EthereumAddressField()


class SafeFundingResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = SafeFunding
        fields = ('safe_funded', 'deployer_funded', 'deployer_funded_tx_hash', 'safe_deployed', 'safe_deployed_tx_hash')


class SafeMultisigTxResponseSerializer(serializers.Serializer):
    transaction_hash = Sha3HashField()


class SafeMultisigEstimateTxResponseSerializer(serializers.Serializer):
    safe_tx_gas = serializers.IntegerField(min_value=0)
    data_gas = serializers.IntegerField(min_value=0)
    signature_gas = serializers.IntegerField(min_value=0)
    gas_price = serializers.IntegerField(min_value=0)
    nonce = serializers.IntegerField(min_value=0)
    gas_token = HexadecimalField(allow_blank=True, allow_null=True)
