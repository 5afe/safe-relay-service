import logging

from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from gnosis.eth.constants import (NULL_ADDRESS, SIGNATURE_S_MAX_VALUE,
                                  SIGNATURE_S_MIN_VALUE, SIGNATURE_V_MAX_VALUE,
                                  SIGNATURE_V_MIN_VALUE, SIGNATURE_R_MIN_VALUE, SIGNATURE_R_MAX_VALUE)
from gnosis.eth.django.serializers import (EthereumAddressField,
                                           HexadecimalField, Sha3HashField,
                                           TransactionResponseSerializer)
from gnosis.safe import SafeOperation
from gnosis.safe.serializers import SafeMultisigTxSerializer

from safe_relay_service.relay.models import (EthereumEvent, EthereumTx,
                                             SafeFunding)

from .services import StatsServiceProvider

logger = logging.getLogger(__name__)


class ThresholdValidatorSerializerMixin:
    def validate(self, data):
        super().validate(data)
        owners = data['owners']
        threshold = data['threshold']

        if threshold > len(owners):
            raise ValidationError("Threshold cannot be greater than number of owners")

        return data


class SafeCreationSerializer(ThresholdValidatorSerializerMixin, serializers.Serializer):
    s = serializers.IntegerField(min_value=SIGNATURE_S_MIN_VALUE, max_value=SIGNATURE_S_MAX_VALUE)
    owners = serializers.ListField(child=EthereumAddressField(), min_length=1)
    threshold = serializers.IntegerField(min_value=1)
    payment_token = EthereumAddressField(default=None, allow_null=True, allow_zero_address=True)
    data = serializers.CharField(default=b'')


class SafeCreation2Serializer(ThresholdValidatorSerializerMixin, serializers.Serializer):
    salt_nonce = serializers.IntegerField(min_value=0, max_value=2**256-1)  # Uint256
    owners = serializers.ListField(child=EthereumAddressField(), min_length=1)
    threshold = serializers.IntegerField(min_value=1)
    payment_token = EthereumAddressField(default=None, allow_null=True, allow_zero_address=True)
    to = EthereumAddressField(default=None, allow_null=True, allow_zero_address=True)
    setup_data = serializers.CharField(default=None, allow_null=True, allow_blank=True, required=False)
    callback = EthereumAddressField(default=None, allow_null=True, allow_zero_address=True)


class SafeCreationEstimateSerializer(serializers.Serializer):
    number_owners = serializers.IntegerField(min_value=1)
    payment_token = EthereumAddressField(default=None, allow_null=True, allow_zero_address=True)


class SafeCreationEstimateV2Serializer(serializers.Serializer):
    number_owners = serializers.IntegerField(min_value=1)


class SafeSignatureSerializer(serializers.Serializer):
    """
    When using safe signatures `v` can have more values
    """
    v = serializers.IntegerField(min_value=0)
    r = serializers.IntegerField(min_value=0)
    s = serializers.IntegerField(min_value=0)

    def validate_v(self, v):
        if v == 0:  # Contract signature
            return v
        elif v == 1:  # Approved hash
            return v
        elif v > 30:  # Support eth_sign
            return v
        elif self.check_v(v):
            return v
        else:
            raise serializers.ValidationError("v should be 0, 1 or be in %d-%d" % (SIGNATURE_V_MIN_VALUE,
                                                                                   SIGNATURE_V_MAX_VALUE))

    def validate(self, data):
        super().validate(data)

        v = data['v']
        r = data['r']
        s = data['s']

        if v not in [0, 1]:  # Disable checks for `r` and `s` if v is 0 or 1
            if not self.check_r(r):
                raise serializers.ValidationError("r not valid")
            elif not self.check_s(s):
                raise serializers.ValidationError("s not valid")
        return data

    def check_v(self, v):
        return SIGNATURE_V_MIN_VALUE <= v <= SIGNATURE_V_MAX_VALUE

    def check_r(self, r):
        return SIGNATURE_R_MIN_VALUE <= r <= SIGNATURE_R_MAX_VALUE

    def check_s(self, s):
        return SIGNATURE_S_MIN_VALUE <= s <= SIGNATURE_S_MAX_VALUE


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
    tokens_with_balance = serializers.SerializerMethodField()

    def get_tokens_with_balance(self, obj):
        return StatsServiceProvider().get_balances(obj.address)


class SafeBalanceResponseSerializer(serializers.Serializer):
    token_address = serializers.CharField()
    balance = serializers.CharField()


class SafeResponseSerializer(serializers.Serializer):
    address = EthereumAddressField()
    master_copy = EthereumAddressField()
    fallback_handler = EthereumAddressField()
    nonce = serializers.IntegerField(min_value=0)
    threshold = serializers.IntegerField(min_value=1)
    owners = serializers.ListField(child=EthereumAddressField(), min_length=1)
    version = serializers.CharField()


class SafeCreationEstimateResponseSerializer(serializers.Serializer):
    gas = serializers.CharField()
    gas_price = serializers.CharField()
    payment = serializers.CharField()
    payment_token = EthereumAddressField(allow_null=True)


class SafeCreationResponseSerializer(serializers.Serializer):
    signature = SignatureResponseSerializer()
    tx = TransactionResponseSerializer()
    tx_hash = Sha3HashField()
    payment = serializers.CharField()
    payment_token = EthereumAddressField(allow_null=True, allow_zero_address=True)
    safe = EthereumAddressField()
    setup_data = serializers.CharField()
    deployer = EthereumAddressField()
    funder = EthereumAddressField()


class SafeCreation2ResponseSerializer(serializers.Serializer):
    safe = EthereumAddressField()
    master_copy = EthereumAddressField()
    proxy_factory = EthereumAddressField()
    payment_token = EthereumAddressField(allow_zero_address=True)
    payment = serializers.CharField()
    payment_receiver = EthereumAddressField(allow_zero_address=True)
    setup_data = HexadecimalField()
    to = EthereumAddressField(allow_zero_address=True)
    gas_estimated = serializers.CharField()
    gas_price_estimated = serializers.CharField()
    callback = EthereumAddressField(allow_zero_address=True)


class SafeFundingResponseSerializer(serializers.ModelSerializer):
    class Meta:
        model = SafeFunding
        fields = ('safe_funded', 'deployer_funded', 'deployer_funded_tx_hash', 'safe_deployed', 'safe_deployed_tx_hash')


class SafeFunding2ResponseSerializer(serializers.Serializer):
    block_number = serializers.CharField()
    tx_hash = Sha3HashField()


class EthereumTxSerializer(serializers.ModelSerializer):
    class Meta:
        model = EthereumTx
        exclude = ('block',)

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
    ethereum_tx = EthereumTxSerializer()
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


class SafeMultisigEstimateTxResponseV2Serializer(serializers.Serializer):
    """
    Same as `SafeMultisigEstimateTxResponseSerializer`, but formatting `big integers` as `strings`
    """
    safe_tx_gas = serializers.CharField()
    base_gas = serializers.CharField()
    data_gas = serializers.CharField()
    operational_gas = serializers.CharField()
    gas_price = serializers.CharField()
    last_used_nonce = serializers.IntegerField(min_value=0, allow_null=True)
    gas_token = EthereumAddressField(allow_null=True, allow_zero_address=True)


class TransactionGasTokenEstimationResponseSerializer(serializers.Serializer):
    base_gas = serializers.CharField()
    gas_price = serializers.CharField()
    gas_token = EthereumAddressField(allow_null=True, allow_zero_address=True)


class TransactionEstimationWithNonceAndGasTokensResponseSerializer(serializers.Serializer):
    last_used_nonce = serializers.IntegerField(min_value=0)
    safe_tx_gas = serializers.CharField()
    operational_gas = serializers.CharField()
    estimations = TransactionGasTokenEstimationResponseSerializer(many=True)
