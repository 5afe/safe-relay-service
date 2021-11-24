import datetime
from datetime import timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Union

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.db.models import (
    Avg,
    Case,
    Count,
    DurationField,
    F,
    JSONField,
    Q,
    Sum,
    Value,
    When,
)
from django.db.models.expressions import RawSQL, Subquery, Window
from django.db.models.functions import Cast, TruncDate
from django.utils import timezone

from hexbytes import HexBytes
from model_utils.models import TimeStampedModel
from web3.types import TxParams

from gnosis.eth import EthereumClient
from gnosis.eth.constants import ERC20_721_TRANSFER_TOPIC, NULL_ADDRESS
from gnosis.eth.django.models import EthereumAddressField, Sha3HashField, Uint256Field
from gnosis.safe import SafeOperation, SafeTx
from gnosis.safe.safe_signature import SafeSignature

from .models_raw import SafeContractManagerRaw, SafeContractQuerySetRaw


class EthereumTxType(Enum):
    CALL = 0
    CREATE = 1
    SELF_DESTRUCT = 2

    @staticmethod
    def parse(tx_type: str):
        tx_type = tx_type.upper()
        if tx_type == "CALL":
            return EthereumTxType.CALL
        elif tx_type == "CREATE":
            return EthereumTxType.CREATE
        elif tx_type == "SUICIDE":
            return EthereumTxType.SELF_DESTRUCT
        else:
            raise ValueError("%s is not a valid EthereumTxType" % tx_type)


class EthereumTxCallType(Enum):
    CALL = 0
    DELEGATE_CALL = 1

    @staticmethod
    def parse_call_type(call_type: str):
        if not call_type:
            return None
        elif call_type.lower() == "call":
            return EthereumTxCallType.CALL
        elif call_type.lower() == "delegatecall":
            return EthereumTxCallType.DELEGATE_CALL
        else:
            return None


class SafeContractManager(SafeContractManagerRaw):
    def get_total_balance(
        self, from_date: datetime.datetime, to_date: datetime.datetime
    ) -> int:
        return int(
            self.with_balance()
            .filter(created__range=(from_date, to_date))
            .aggregate(total_balance=Sum("balance"))
            .get("total_balance")
            or 0
        )


class SafeContractQuerySet(SafeContractQuerySetRaw):
    deployed_filter = ~Q(safecreation2__block_number=None) | Q(
        safefunding__safe_deployed=True
    )

    def deployed(self):
        return self.filter(self.deployed_filter)

    def not_deployed(self):
        return self.exclude(self.deployed_filter)


class SafeContract(TimeStampedModel):
    objects = SafeContractManager.from_queryset(SafeContractQuerySet)()
    address = EthereumAddressField(primary_key=True)
    master_copy = EthereumAddressField()

    def __str__(self):
        return "Safe=%s Master-copy=%s" % (self.address, self.master_copy)

    def get_tokens_with_balance(self) -> List[Dict[str, Any]]:
        return EthereumEvent.objects.erc20_tokens_with_balance(self.address)


class SafeCreationManager(models.Manager):
    def get_tokens_usage(self) -> Optional[List[Dict[str, Any]]]:
        """
        :return: List of Dict 'gas_token', 'total', 'number', 'percentage'
        """
        total = (
            self.deployed_and_checked()
            .annotate(_x=Value(1))
            .values("_x")
            .annotate(total=Count("_x"))
            .values("total")
        )
        return (
            self.deployed_and_checked()
            .values("payment_token")
            .annotate(total=Subquery(total, output_field=models.IntegerField()))
            .annotate(
                number=Count("safe_id"),
                percentage=Cast(100.0 * Count("pk") / F("total"), models.FloatField()),
            )
        )


class SafeCreation(TimeStampedModel):
    objects = SafeCreationManager()
    deployer = EthereumAddressField(primary_key=True)
    safe = models.OneToOneField(SafeContract, on_delete=models.CASCADE)
    master_copy = EthereumAddressField()
    funder = EthereumAddressField(null=True)
    owners = ArrayField(EthereumAddressField())
    threshold = Uint256Field()
    payment = Uint256Field()
    tx_hash = Sha3HashField(unique=True)
    gas = Uint256Field()
    gas_price = Uint256Field()
    payment_token = EthereumAddressField(null=True)
    value = Uint256Field()
    v = models.PositiveSmallIntegerField()
    r = Uint256Field()
    s = Uint256Field()
    data = models.BinaryField(null=True)
    signed_tx = models.BinaryField(null=True)

    def __str__(self):
        return "Safe {} - Deployer {}".format(self.safe, self.deployer)

    def wei_deploy_cost(self) -> int:
        """
        :return: int: Cost to deploy the contract in wei
        """
        return self.gas * self.gas_price


class SafeCreation2QuerySet(models.QuerySet):
    def deployed_and_checked(self):
        return self.exclude(
            tx_hash=None,
            block_number=None,
        ).select_related("safe")

    def not_deployed(self):
        return self.filter(tx_hash=None)

    def pending_to_check(self):
        return (
            self.exclude(
                tx_hash=None,
            )
            .filter(
                block_number=None,
            )
            .select_related("safe")
        )


class SafeCreation2(TimeStampedModel):
    objects = SafeCreationManager.from_queryset(SafeCreation2QuerySet)()
    safe = models.OneToOneField(
        SafeContract, on_delete=models.CASCADE, primary_key=True
    )
    master_copy = EthereumAddressField()
    proxy_factory = EthereumAddressField()
    salt_nonce = Uint256Field()
    owners = ArrayField(EthereumAddressField())
    threshold = Uint256Field()
    # to = EthereumAddressField(null=True)  # Contract address for optional delegate call
    # data = models.BinaryField(null=True)  # Data payload for optional delegate call
    payment_token = EthereumAddressField(null=True)
    payment = Uint256Field()
    payment_receiver = EthereumAddressField(null=True)  # If empty, `tx.origin` is used
    setup_data = models.BinaryField(null=True)  # Binary data for safe `setup` call
    gas_estimated = Uint256Field()
    gas_price_estimated = Uint256Field()
    tx_hash = Sha3HashField(unique=True, null=True, default=None)
    block_number = models.IntegerField(null=True, default=None)  # If mined

    class Meta:
        verbose_name_plural = "Safe creation2s"

    def __str__(self):
        if self.block_number:
            return "Safe {} - Deployed on block number {}".format(
                self.safe, self.block_number
            )
        else:
            return "Safe {}".format(self.safe)

    def deployed(self) -> bool:
        return self.block_number is not None

    def wei_estimated_deploy_cost(self) -> int:
        """
        :return: int: Cost to deploy the contract in wei
        """
        return self.gas_estimated * self.gas_price_estimated

    def gas_used(self) -> Optional[int]:
        """
        :return: Gas used by the transaction if it was executed
        """
        if self.tx_hash:
            try:
                return EthereumTx.objects.get(tx_hash=self.tx_hash).gas_used
            except EthereumTx.DoesNotExist:
                return None


class SafeFundingQuerySet(models.QuerySet):
    def pending_just_to_deploy(self):
        return (
            self.filter(safe_deployed=False)
            .filter(deployer_funded=True)
            .select_related("safe")
        )

    def not_deployed(self):
        return self.filter(safe_deployed=False).select_related("safe")


class SafeFunding(TimeStampedModel):
    objects = SafeFundingQuerySet.as_manager()
    safe = models.OneToOneField(
        SafeContract, primary_key=True, on_delete=models.CASCADE
    )
    safe_funded = models.BooleanField(default=False)
    deployer_funded = models.BooleanField(
        default=False, db_index=True
    )  # Set when deployer_funded_tx_hash is mined
    deployer_funded_tx_hash = Sha3HashField(unique=True, blank=True, null=True)
    safe_deployed = models.BooleanField(
        default=False, db_index=True
    )  # Set when safe_deployed_tx_hash is mined
    # We could use SafeCreation.tx_hash, but we would run into troubles because of Ganache
    safe_deployed_tx_hash = Sha3HashField(unique=True, blank=True, null=True)

    def is_all_funded(self):
        return self.safe_funded and self.deployer_funded

    def status(self):
        if self.safe_deployed:
            return "DEPLOYED"
        elif self.safe_deployed_tx_hash:
            return "DEPLOYED_UNCHECKED"
        elif self.deployer_funded:
            return "DEPLOYER_FUNDED"
        elif self.deployer_funded_tx_hash:
            return "DEPLOYER_FUNDED_UNCHECKED"
        elif self.safe_funded:
            return "DEPLOYER_NOT_FUNDED_SAFE_WITH_BALANCE"
        else:
            return "SAFE_WITHOUT_BALANCE"

    def __str__(self):
        s = "Safe %s - " % self.safe.address
        if self.safe_deployed:
            s += "deployed"
        elif self.safe_deployed_tx_hash:
            s += "deployed but not checked"
        elif self.deployer_funded:
            s += "with deployer funded"
        elif self.deployer_funded_tx_hash:
            s += "with deployer funded but not checked"
        elif self.safe_funded:
            s += "has enough balance, but deployer is not funded yet"
        else:
            s = "Safe %s" % self.safe.address
        return s


class EthereumBlockManager(models.Manager):
    def create_from_block(self, block: Dict[str, Any]) -> "EthereumBlock":
        return super().create(
            number=block["number"],
            gas_limit=block["gasLimit"],
            gas_used=block["gasUsed"],
            timestamp=datetime.datetime.fromtimestamp(
                block["timestamp"], datetime.timezone.utc
            ),
            block_hash=block["hash"],
        )


class EthereumBlock(models.Model):
    objects = EthereumBlockManager()
    number = models.PositiveIntegerField(primary_key=True, unique=True)
    gas_limit = models.PositiveIntegerField()
    gas_used = models.PositiveIntegerField()
    timestamp = models.DateTimeField()
    block_hash = Sha3HashField(unique=True)

    def __str__(self):
        return f"Block={self.number} on {self.timestamp}"


class EthereumTxManager(models.Manager):
    def create_from_tx_dict(
        self,
        tx: Dict[str, Any],
        tx_hash: Union[bytes, str],
        tx_receipt: Optional[Dict[str, Any]] = None,
        ethereum_block: Optional[EthereumBlock] = None,
    ) -> "EthereumTx":
        data = HexBytes(tx.get("data") or tx.get("input"))
        # Supporting EIP1559
        max_fee_per_gas = tx.get("maxFeePerGas", 0)
        max_priority_fee_per_gas = tx.get("maxPriorityFeePerGas", 0)
        gas_price = tx.get("gasPrice", max_fee_per_gas)
        return super().create(
            block=ethereum_block,
            tx_hash=tx_hash,
            _from=tx["from"],
            gas=tx["gas"],
            gas_price=gas_price,
            gas_used=tx_receipt and tx_receipt["gasUsed"],
            status=tx_receipt and tx_receipt.get("status"),
            transaction_index=tx_receipt and tx_receipt["transactionIndex"],
            data=data if data else None,
            nonce=tx["nonce"],
            to=tx.get("to"),
            value=tx["value"],
            max_fee_per_gas=max_fee_per_gas,
            max_priority_fee_per_gas=max_priority_fee_per_gas,
        )


class EthereumTx(TimeStampedModel):
    objects = EthereumTxManager()
    block = models.ForeignKey(
        EthereumBlock,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        default=None,
        related_name="txs",
    )  # If mined
    tx_hash = Sha3HashField(unique=True, primary_key=True)
    gas_used = Uint256Field(null=True, blank=True, default=None)  # If mined
    status = models.IntegerField(
        null=True, blank=True, default=None, db_index=True
    )  # If mined. Old txs don't have `status`
    transaction_index = models.PositiveIntegerField(
        null=True, blank=True, default=None
    )  # If mined
    _from = EthereumAddressField(null=True, db_index=True)
    gas = Uint256Field()
    gas_price = Uint256Field()
    data = models.BinaryField(null=True, blank=True)
    nonce = Uint256Field()
    to = EthereumAddressField(null=True, blank=True, db_index=True)
    value = Uint256Field()
    max_fee_per_gas = Uint256Field(default=0)
    max_priority_fee_per_gas = Uint256Field(default=0)

    def __str__(self):
        return "{} status={} from={} to={}".format(
            self.tx_hash, self.status, self._from, self.to
        )

    @property
    def success(self) -> Optional[bool]:
        if self.status is not None:
            return self.status == 1

    @property
    def fee(self) -> int:
        return self.gas * self.gas_price

    def is_eip1559(self):
        return self.max_fee_per_gas or self.max_priority_fee_per_gas

    def as_tx_dict(self) -> TxParams:
        tx_params: TxParams = {
            "data": bytes(self.data) if self.data else b"",
            "from": self._from,
            "gas": self.gas,
            "gasPrice": self.gas_price,
            "nonce": self.nonce,
            "to": self.to,
            "value": self.value,
        }
        if self.is_eip1559():
            tx_params["maxFeePerGas"] = self.max_fee_per_gas
            tx_params["maxPriorityFeePerGas"] = self.max_priority_fee_per_gas
        else:
            tx_params["gasPrice"] = self.gas_price
        return tx_params


class SafeMultisigTxManager(models.Manager):
    def get_last_nonce_for_safe(self, safe_address: str) -> Optional[int]:
        """
        Get last nonce for Safe from transactions pending/executed successfully, excluding failed transactions
        :param safe_address:
        :return:
        """
        nonce_dict = (
            self.filter(safe=safe_address)
            .not_failed()
            .order_by("-nonce")
            .values("nonce")
            .first()
        )
        return nonce_dict["nonce"] if nonce_dict else None

    def get_average_execution_time(
        self, from_date: datetime.datetime, to_date: datetime.datetime
    ) -> Optional[datetime.timedelta]:
        return (
            self.select_related("ethereum_tx", "ethereum_tx__block")
            .exclude(
                ethereum_tx__block=None,
            )
            .annotate(
                interval=Cast(
                    F("ethereum_tx__block__timestamp") - F("created"),
                    output_field=DurationField(),
                )
            )
            .filter(created__range=(from_date, to_date))
            .aggregate(median=Avg("interval"))["median"]
        )

    def get_average_execution_time_grouped(
        self, from_date: datetime.datetime, to_date: datetime.datetime
    ) -> Optional[datetime.timedelta]:
        return (
            self.select_related("ethereum_tx", "ethereum_tx__block")
            .exclude(
                ethereum_tx__block=None,
            )
            .annotate(
                interval=Cast(
                    F("ethereum_tx__block__timestamp") - F("created"),
                    output_field=DurationField(),
                )
            )
            .filter(created__range=(from_date, to_date))
            .annotate(created_date=TruncDate("created"))
            .values("created_date")
            .annotate(average_execution_time=Avg("interval"))
            .values("created_date", "average_execution_time")
            .order_by("created_date")
        )

    def get_tokens_usage(self) -> Optional[List[Dict[str, Any]]]:
        """
        :return: List of Dict 'gas_token', 'total', 'number', 'percentage'
        """
        total = (
            self.annotate(_x=Value(1))
            .values("_x")
            .annotate(total=Count("_x"))
            .values("total")
        )
        return (
            self.values("gas_token")
            .annotate(total=Subquery(total, output_field=models.IntegerField()))
            .annotate(
                number=Count("pk"),
                percentage=Cast(100.0 * Count("pk") / F("total"), models.FloatField()),
            )
        )

    def get_tokens_usage_grouped(self) -> Optional[List[Dict[str, Any]]]:
        """
        :return: List of Dict 'gas_token', 'total', 'number', 'percentage'
        """
        return (
            SafeMultisigTx.objects.annotate(date=TruncDate("created"))
            .annotate(
                number=Window(
                    expression=Count("*"), partition_by=[F("gas_token"), F("date")]
                ),
                percentage=100.0
                * Window(
                    expression=Count("*"), partition_by=[F("gas_token"), F("date")]
                )
                / Window(expression=Count("*"), partition_by=[F("date")]),
            )
            .values("date", "gas_token", "number", "percentage")
            .distinct()
            .order_by("date")
        )


class SafeMultisigTxQuerySet(models.QuerySet):
    def failed(self):
        """
        :return: Mined and failed transactions
        """
        return self.exclude(ethereum_tx__status=None).exclude(ethereum_tx__status=1)

    def not_failed(self):
        """
        :return: Not failed or not mined
        """
        return self.filter(
            Q(ethereum_tx__status=1)
            | Q(
                ethereum_tx__status=None
            )  # No failed transactions, just success or not mined
        )

    def pending(self, older_than: int = 0):
        """
        Get multisig txs that have not been mined after `older_than` seconds
        :param older_than: Time in seconds for a tx to be considered pending, if 0 all will be returned
        """
        not_mined_filter = self.filter(
            Q(ethereum_tx__block=None)
            | Q(ethereum_tx=None)  # Just in case, but ethereum_tx cannot be null
        )
        if older_than:
            return not_mined_filter.filter(
                created__lte=timezone.now() - timedelta(seconds=older_than),
            )
        else:
            return not_mined_filter

    def successful(self):
        """
        :return: Mined and successful transactions
        """
        return self.filter(ethereum_tx__status=1)


class SafeMultisigTx(TimeStampedModel):
    objects = SafeMultisigTxManager.from_queryset(SafeMultisigTxQuerySet)()
    safe = models.ForeignKey(
        SafeContract, on_delete=models.CASCADE, related_name="multisig_txs"
    )
    ethereum_tx = models.ForeignKey(
        EthereumTx, on_delete=models.CASCADE, related_name="multisig_txs"
    )
    to = EthereumAddressField(null=True, blank=True, db_index=True)
    value = Uint256Field()
    data = models.BinaryField(null=True, blank=True)
    operation = models.PositiveSmallIntegerField(
        choices=[(tag.value, tag.name) for tag in SafeOperation]
    )
    safe_tx_gas = Uint256Field()
    data_gas = Uint256Field()
    gas_price = Uint256Field()
    gas_token = EthereumAddressField(null=True, blank=True)
    refund_receiver = EthereumAddressField(null=True, blank=True)
    signatures = models.BinaryField()
    nonce = Uint256Field()
    safe_tx_hash = Sha3HashField(unique=True, null=True, blank=True)

    def __str__(self):
        return "{} - {} - Safe {}".format(
            self.ethereum_tx.tx_hash,
            SafeOperation(self.operation).name,
            self.safe.address,
        )

    def get_safe_tx(self, ethereum_client: EthereumClient) -> SafeTx:
        return SafeTx(
            ethereum_client,
            self.safe_id,
            self.to,
            self.value,
            self.data.tobytes() if self.data else b"",
            self.operation,
            self.safe_tx_gas,
            self.data_gas,
            self.gas_price,
            self.gas_token,
            self.refund_receiver,
            signatures=self.signatures.tobytes() if self.signatures else b"",
            safe_nonce=self.nonce,
        )

    def refund_benefit(self) -> Optional[int]:
        """
        :return: Difference of the calculated payment fee and the actual executed payment fee. It will be `None`
        if transaction was not mined yet or if a `gas_token` was used (not easy to calculate the ether conversion
        at that point)
        """
        if (
            self.ethereum_tx_id
            and (not self.gas_token or self.gas_token == NULL_ADDRESS)
            and self.ethereum_tx.gas_used
        ):
            payment_fee = min(self.gas_price, self.ethereum_tx.gas_price)
            executed_fee = self.ethereum_tx.gas_used * self.ethereum_tx.gas_price
            return payment_fee - executed_fee

    def signers(self) -> List[str]:
        if not self.signatures:
            return []
        else:
            signatures = bytes(self.signatures)
            safe_signatures = SafeSignature.parse_signature(
                signatures, self.safe_tx_hash
            )
            return [safe_signature.owner for safe_signature in safe_signatures]


class SafeTxStatusQuerySet(models.QuerySet):
    def deployed(self):
        return self.filter(safe__in=SafeContract.objects.deployed())


class SafeTxStatus(models.Model):
    """
    Have information about the last scan for internal txs
    """

    objects = SafeTxStatusQuerySet.as_manager()
    safe = models.OneToOneField(
        SafeContract, primary_key=True, on_delete=models.CASCADE
    )
    initial_block_number = models.IntegerField(
        default=0
    )  # Block number when Safe creation process was started
    tx_block_number = models.IntegerField(
        default=0
    )  # Block number when last internal tx scan ended
    erc_20_block_number = models.IntegerField(
        default=0
    )  # Block number when last erc20 events scan ended

    class Meta:
        verbose_name_plural = "Safe tx status"

    def __str__(self):
        return (
            "Safe {} - Initial-block-number={} - "
            "Tx-block-number={} - Erc20-block-number={}".format(
                self.safe.address,
                self.initial_block_number,
                self.tx_block_number,
                self.erc_20_block_number,
            )
        )


class EthereumEventQuerySet(models.QuerySet):
    def not_erc_20_721_events(self):
        return self.exclude(topic=ERC20_721_TRANSFER_TOPIC)

    def erc20_and_721_events(
        self, token_address: Optional[str] = None, address: Optional[str] = None
    ):
        queryset = self.filter(topic=ERC20_721_TRANSFER_TOPIC)
        if token_address:
            queryset = queryset.filter(token_address=token_address)
        if address:
            queryset = queryset.filter(
                Q(arguments__to=address) | Q(arguments__from=address)
            )
        return queryset

    def erc20_events(
        self, token_address: Optional[str] = None, address: Optional[str] = None
    ):
        return self.erc20_and_721_events(
            token_address=token_address, address=address
        ).filter(arguments__has_key="value")

    def erc721_events(
        self, token_address: Optional[str] = None, address: Optional[str] = None
    ):
        return self.erc20_and_721_events(
            token_address=token_address, address=address
        ).filter(arguments__has_key="tokenId")


class EthereumEventManager(models.Manager):
    def erc20_tokens_used_by_address(self, address: str) -> List[str]:
        """
        :param address:
        :return: List of token addresses used by an address
        """
        return (
            self.erc20_events(address=address)
            .values_list("token_address", flat=True)
            .distinct()
        )

    def erc20_tokens_with_balance(self, address: str) -> List[Dict[str, Any]]:
        """
        :return: List of dictionaries {'token_address': str, 'balance': int}
        """
        arguments_value_field = RawSQL("(arguments->>'value')::numeric", ())
        return (
            self.erc20_events(address=address)
            .values("token_address")
            .annotate(
                balance=Sum(
                    Case(
                        When(arguments__from=address, then=-arguments_value_field),
                        default=arguments_value_field,
                    )
                )
            )
            .order_by("-balance")
            .values("token_address", "balance")
        )

    def get_or_create_erc20_or_721_event(self, decoded_event: Dict[str, Any]):
        if "value" in decoded_event["args"]:
            return self.get_or_create_erc20_event(decoded_event)
        elif "tokenId" in decoded_event["args"]:
            return self.get_or_create_erc721_event(decoded_event)
        raise ValueError("Invalid ERC20 or ERC721 event %s" % decoded_event)

    def get_or_create_erc20_event(self, decoded_event: Dict[str, Any]):
        return self.get_or_create(
            ethereum_tx_id=decoded_event["transactionHash"],
            log_index=decoded_event["logIndex"],
            defaults={
                "token_address": decoded_event["address"],
                "topic": decoded_event["topics"][0],
                "arguments": {
                    "from": decoded_event["args"]["from"],
                    "to": decoded_event["args"]["to"],
                    "value": decoded_event["args"]["value"],
                },
            },
        )

    def get_or_create_erc721_event(self, decoded_event: Dict[str, Any]):
        return self.get_or_create(
            ethereum_tx_id=decoded_event["transactionHash"],
            log_index=decoded_event["logIndex"],
            defaults={
                "token_address": decoded_event["address"],
                "topic": decoded_event["topics"][0],
                "arguments": {
                    "from": decoded_event["args"]["from"],
                    "to": decoded_event["args"]["to"],
                    "tokenId": decoded_event["args"]["tokenId"],
                },
            },
        )


class EthereumEvent(models.Model):
    objects = EthereumEventManager.from_queryset(EthereumEventQuerySet)()
    ethereum_tx = models.ForeignKey(
        EthereumTx, on_delete=models.CASCADE, related_name="events"
    )
    log_index = models.PositiveIntegerField()
    token_address = EthereumAddressField(db_index=True)
    topic = Sha3HashField(db_index=True)
    arguments = JSONField()

    class Meta:
        unique_together = (("ethereum_tx", "log_index"),)

    def __str__(self):
        return "Tx-hash={} Log-index={} Arguments={}".format(
            self.ethereum_tx_id, self.log_index, self.arguments
        )

    def is_erc20(self) -> bool:
        return "value" in self.arguments

    def is_erc721(self) -> bool:
        return "tokenId" in self.arguments


class BannedSigner(models.Model):
    address = EthereumAddressField(primary_key=True)

    def __str__(self):
        return self.address
