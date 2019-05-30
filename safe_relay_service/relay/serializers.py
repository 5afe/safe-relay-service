import logging
from typing import Optional

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from gnosis.eth.constants import (NULL_ADDRESS, SIGNATURE_S_MAX_VALUE,
                                  SIGNATURE_S_MIN_VALUE)
from gnosis.eth.django.serializers import (EthereumAddressField,
                                           HexadecimalField, Sha3HashField,
                                           TransactionResponseSerializer)
from gnosis.safe import SafeOperation
from gnosis.safe.serializers import (SafeMultisigTxSerializer,
                                     SafeSignatureSerializer)

from safe_relay_service.relay.models import (EthereumEvent, EthereumTx,
                                             EthereumTxCallType, InternalTx,
                                             SafeCreation2, SafeFunding)

logger = logging.getLogger(__name__)


class SafeCreationSerializer(serializers.Serializer):
    s = serializers.IntegerField(min_value=SIGNATURE_S_MIN_VALUE,
                                 max_value=SIGNATURE_S_MAX_VALUE)
    owners = serializers.ListField(child=EthereumAddressField(), min_length=1)
    threshold = serializers.IntegerField(min_value=1)
    payment_token = EthereumAddressField(default=None, allow_null=True, allow_zero_address=True)

    def validate(self, data):
        super().validate(data)
        owners = data['owners']
        threshold = data['threshold']

        if threshold > len(owners):
            raise ValidationError("Threshold cannot be greater than number of owners")

        return data


class SafeCreation2Serializer(serializers.Serializer):
    salt_nonce = serializers.IntegerField(min_value=0,
                                          max_value=2**256-1)
    owners = serializers.ListField(child=EthereumAddressField(), min_length=1)
    threshold = serializers.IntegerField(min_value=1)
    payment_token = EthereumAddressField(default=None, allow_null=True, allow_zero_address=True)

    def validate(self, data):
        super().validate(data)
        owners = data['owners']
        threshold = data['threshold']

        if threshold > len(owners):
            raise ValidationError("Threshold cannot be greater than number of owners")

        return data


class SafeCreationEstimateSerializer(serializers.Serializer):
    number_owners = serializers.IntegerField(min_value=1)
    payment_token = EthereumAddressField(default=None, allow_null=True, allow_zero_address=True)


class SafeCreationEstimateV2Serializer(serializers.Serializer):
    number_owners = serializers.IntegerField(min_value=1)


# TODO Rename this
class SafeRelayMultisigTxSerializer(SafeMultisigTxSerializer):
    signatures = serializers.ListField(child=SafeSignatureSerializer())

    def validate_refund_receiver(self, refund_receiver):
        if refund_receiver and refund_receiver != NULL_ADDRESS:
            raise ValidationError('Refund Receiver is not configurable')
        return refund_receiver


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


class TokensWithBalanceSerializer(serializers.Serializer):
    token_address = EthereumAddressField()
    balance = serializers.IntegerField()


class SafeContractSerializer(serializers.Serializer):
    created = serializers.DateTimeField()
    address = EthereumAddressField()
    balance = serializers.IntegerField(min_value=0, allow_null=True)
    tokens_with_balance = TokensWithBalanceSerializer(many=True)


class SafeResponseSerializer(serializers.Serializer):
    address = EthereumAddressField()
    master_copy = EthereumAddressField()
    nonce = serializers.IntegerField(min_value=0)
    threshold = serializers.IntegerField(min_value=1)
    owners = serializers.ListField(child=EthereumAddressField(), min_length=1)
    version = serializers.CharField()


class SafeCreationEstimateResponseSerializer(serializers.Serializer):
    gas = serializers.IntegerField(min_value=0)
    gas_price = serializers.IntegerField(min_value=0)
    payment = serializers.IntegerField(min_value=0)
    payment_token = EthereumAddressField(allow_null=True)


class SafeCreationResponseSerializer(serializers.Serializer):
    signature = SignatureResponseSerializer()
    tx = TransactionResponseSerializer()
    tx_hash = Sha3HashField()
    payment = serializers.CharField()
    payment_token = EthereumAddressField(allow_null=True, allow_zero_address=True)
    safe = EthereumAddressField()
    deployer = EthereumAddressField()
    funder = EthereumAddressField()


class SafeCreation2ResponseSerializer(serializers.Serializer):
    safe = EthereumAddressField()
    master_copy = EthereumAddressField()
    proxy_factory = EthereumAddressField()
    payment_token = EthereumAddressField(allow_zero_address=True)
    payment = serializers.IntegerField(min_value=0)
    payment_receiver = EthereumAddressField(allow_zero_address=True)
    setup_data = HexadecimalField()
    gas_estimated = serializers.IntegerField(min_value=0)
    gas_price_estimated = serializers.IntegerField(min_value=0)


class SafeFundingResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = SafeFunding
        fields = ('safe_funded', 'deployer_funded', 'deployer_funded_tx_hash', 'safe_deployed', 'safe_deployed_tx_hash')


class SafeFunding2ResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = SafeCreation2
        fields = ('tx_hash', 'block_number')


class InternalTxSerializer(serializers.ModelSerializer):
    class Meta:
        model = InternalTx
        exclude = ('id',)

    _from = EthereumAddressField(allow_null=False, allow_zero_address=True, source='_from')
    to = EthereumAddressField(allow_null=True, allow_zero_address=True)
    contract_address = EthereumAddressField(allow_null=True, allow_zero_address=True)
    data = HexadecimalField()
    code = HexadecimalField()
    output = HexadecimalField()
    call_type = serializers.SerializerMethodField()
    tx_type = serializers.SerializerMethodField()
    ethereum_tx = None

    def get_fields(self):
        result = super().get_fields()
        # Rename `_from` to `from`
        _from = result.pop('_from')
        result['from'] = _from
        return result

    def get_call_type(self, obj) -> str:
        if obj.call_type is None:
            return None
        else:
            return EthereumTxCallType(obj.call_type).name

    def get_tx_type(self, obj) -> str:
        return obj.tx_type().name


class EthereumTxSerializer(serializers.ModelSerializer):
    class Meta:
        model = EthereumTx
        exclude = ()

    _from = EthereumAddressField(allow_null=False, allow_zero_address=True, source='_from')
    to = EthereumAddressField(allow_null=True, allow_zero_address=True)
    data = HexadecimalField()
    tx_hash = HexadecimalField()
    block_number = serializers.SerializerMethodField()
    block_timestamp = serializers.SerializerMethodField()

    def get_fields(self):
        result = super().get_fields()
        # Rename `_from` to `from`
        _from = result.pop('_from')
        result['from'] = _from
        return result

    def get_block_number(self, obj: EthereumTx):
        if obj.block:
            return obj.block.number

    def get_block_timestamp(self, obj: EthereumTx):
        if obj.block:
            return obj.block.timestamp


class InternalTxWithEthereumTxSerializer(InternalTxSerializer):
    ethereum_tx = EthereumTxSerializer()


class EthereumTxWithInternalTxsSerializer(EthereumTxSerializer):
    internal_txs = InternalTxSerializer(many=True)


class ERCTransfer(serializers.ModelSerializer):
    """
    Base class for ERC20 and ERC721 serializer
    """
    class Meta:
        model = EthereumEvent
        exclude = ('arguments', 'topic')

    ethereum_tx = EthereumTxSerializer()
    log_index = serializers.IntegerField(min_value=0)
    token_address = EthereumAddressField()
    _from = EthereumAddressField(allow_null=False, allow_zero_address=True, source='arguments.from')
    to = EthereumAddressField(allow_null=False, allow_zero_address=True, source='arguments.to')

    def get_fields(self):
        result = super().get_fields()
        # Rename `_from` to `from`
        _from = result.pop('_from')
        result['from'] = _from
        return result


class ERC20Serializer(ERCTransfer):
    value = serializers.CharField(source='arguments.value')


class ERC721Serializer(ERCTransfer):
    token_id = serializers.CharField(source='arguments.tokenId')


class SafeMultisigTxResponseSerializer(serializers.Serializer):
    to = EthereumAddressField(allow_null=True, allow_zero_address=True)
    ethereum_tx = EthereumTxWithInternalTxsSerializer()
    value = serializers.IntegerField(min_value=0)
    data = HexadecimalField()
    timestamp = serializers.DateTimeField(source='created')
    operation = serializers.SerializerMethodField()
    safe_tx_gas = serializers.IntegerField(min_value=0)
    data_gas = serializers.IntegerField(min_value=0)
    gas_price = serializers.IntegerField(min_value=0)
    gas_token = EthereumAddressField(allow_null=True, allow_zero_address=True)
    refund_receiver = EthereumAddressField(allow_null=True, allow_zero_address=True)
    nonce = serializers.IntegerField(min_value=0)
    safe_tx_hash = Sha3HashField()
    tx_hash = serializers.SerializerMethodField()
    transaction_hash = serializers.SerializerMethodField(method_name='get_tx_hash')  # Retro compatibility

    def get_operation(self, obj):
        """
        Filters confirmations queryset
        :param obj: MultisigConfirmation instance
        :return: serialized queryset
        """
        return SafeOperation(obj.operation).name

    def get_tx_hash(self, obj):
        tx_hash = obj.ethereum_tx.tx_hash
        if tx_hash and isinstance(tx_hash, bytes):
            return tx_hash.hex()
        return tx_hash


class SafeMultisigEstimateTxResponseSerializer(serializers.Serializer):
    safe_tx_gas = serializers.IntegerField(min_value=0)
    base_gas = serializers.IntegerField(min_value=0)
    data_gas = serializers.IntegerField(min_value=0)
    operational_gas = serializers.IntegerField(min_value=0)
    gas_price = serializers.IntegerField(min_value=0)
    last_used_nonce = serializers.IntegerField(min_value=0, allow_null=True)
    gas_token = EthereumAddressField(allow_null=True, allow_zero_address=True)


class TransactionGasTokenEstimationResponseSerializer(serializers.Serializer):
    base_gas = serializers.IntegerField(min_value=0)
    gas_price = serializers.IntegerField(min_value=0)
    gas_token = EthereumAddressField(allow_null=True, allow_zero_address=True)


class TransactionEstimationWithNonceAndGasTokensResponseSerializer(serializers.Serializer):
    last_used_nonce = serializers.IntegerField(min_value=0)
    safe_tx_gas = serializers.IntegerField(min_value=0)
    operational_gas = serializers.IntegerField(min_value=0)
    estimations = TransactionGasTokenEstimationResponseSerializer(many=True)
