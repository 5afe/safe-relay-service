import logging

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from django_eth.constants import SIGNATURE_S_MAX_VALUE, SIGNATURE_S_MIN_VALUE
from django_eth.serializers import (EthereumAddressField, HexadecimalField,
                                    Sha3HashField, SignatureSerializer,
                                    TransactionResponseSerializer)
from gnosis.safe.ethereum_service import EthereumServiceProvider
from gnosis.safe.safe_service import SafeOperation, SafeServiceProvider
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


class SafeMultisigEstimateTxSerializer(serializers.Serializer):
    safe = EthereumAddressField()
    to = EthereumAddressField(default=None, allow_null=True)
    value = serializers.IntegerField(min_value=0)
    data = HexadecimalField(default=None, allow_null=True, allow_blank=True)
    operation = serializers.IntegerField(min_value=0, max_value=2)  # Call, DelegateCall or Create

    def validate_operation(self, value):
        try:
            SafeOperation(value)
            return value
        except ValueError:
            raise ValidationError('Unknown operation')

    def validate(self, data):
        super().validate(data)

        if not data['to'] and not data['data']:
            raise ValidationError('`data` and `to` cannot both be null')

        if not data['to'] and not data['data']:
            raise ValidationError('`data` and `to` cannot both be null')

        if data['operation'] == SafeOperation.CREATE.value:
            if data['to']:
                raise ValidationError('Operation is Create, but `to` was provided')
            elif not data['data']:
                raise ValidationError('Operation is Create, but not `data` was provided')
        elif not data['to']:
            raise ValidationError('Operation is not create, but `to` was not provided')

        return data


class SafeMultisigTxSerializer(SafeMultisigEstimateTxSerializer):
    safe_tx_gas = serializers.IntegerField(min_value=0)
    data_gas = serializers.IntegerField(min_value=0)
    gas_price = serializers.IntegerField(min_value=0)
    gas_token = EthereumAddressField(default=None, allow_null=True)
    refund_receiver = EthereumAddressField(default=None, allow_null=True)
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

        if data.get('gas_token'):
            raise ValidationError('Gas Token is still not supported')

        tx_hash = safe_service.get_hash_for_safe_tx(data['safe'], data['to'], data['value'], data['data'],
                                                    data['operation'], data['safe_tx_gas'], data['data_gas'],
                                                    data['gas_price'], data['gas_token'], data['refund_receiver'],
                                                    data['nonce'])

        owners = [EthereumServiceProvider().get_signing_address(tx_hash,
                                                                signature['v'],
                                                                signature['r'],
                                                                signature['s']) for signature in signatures]

        # FIXME Check owners in blockchain instead of DB
        # for owner in owners:
        #    if owner not in safe_creation.owners:
        #        raise ValidationError('Owner=%s is not a member of the safe' % owner)

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
    gas_price = serializers.IntegerField(min_value=0)
    gas_token = HexadecimalField(allow_blank=True, allow_null=True)
