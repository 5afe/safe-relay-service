from enum import Enum
from typing import Dict, List, Optional

from django.contrib.postgres.fields import ArrayField, JSONField
from django.db import models
from django.db.models import Case, DecimalField, F, Q, Sum, When
from django.db.models.expressions import OuterRef, RawSQL, Subquery

from hexbytes import HexBytes
from model_utils.models import TimeStampedModel

from gnosis.eth.constants import ERC20_721_TRANSFER_TOPIC
from gnosis.eth.django.models import (EthereumAddressField, Sha3HashField,
                                      Uint256Field)
from gnosis.safe import SafeOperation


class EthereumTxType(Enum):
    CALL = 0
    CREATE = 1


class EthereumTxCallType(Enum):
    CALL = 0
    DELEGATE_CALL = 1

    @staticmethod
    def parse_call_type(call_type: str):
        if not call_type:
            return None
        elif call_type.lower() == 'call':
            return EthereumTxCallType.CALL
        elif call_type.lower() == 'delegatecall':
            return EthereumTxCallType.DELEGATE_CALL
        else:
            return None


class SafeContractQuerySet(models.QuerySet):
    def deployed(self):
        return self.filter(
            ~Q(safecreation2__block_number=None) | Q(safefunding__safe_deployed=True)
        )

    def not_deployed(self):
        return self.filter(
            Q(safecreation2__block_number=None) & ~Q(safefunding__safe_deployed=True)
        )


class SafeContract(TimeStampedModel):
    objects = SafeContractQuerySet.as_manager()
    address = EthereumAddressField(primary_key=True)
    master_copy = EthereumAddressField()

    def __str__(self):
        return 'Safe=%s Master-copy=%s' % (self.address, self.master_copy)

    def _balance(self) -> Optional[int]:
        return InternalTx.objects.calculate_balance(self.address)
    balance = property(_balance)

    def _tokens_with_balance(self) -> List[Dict[str, any]]:
        """
        :return: List of dictionaries {'token_address': str, 'balance': int}
        """
        address = self.address
        arguments_value_field = RawSQL("(arguments->>'value')::numeric", ())
        return EthereumEvent.objects.erc20_events(
            address=address
        ).values('token_address').annotate(
            balance=Sum(Case(
                When(arguments__from=address, then=-arguments_value_field),
                default=arguments_value_field,
            ))
        ).order_by('-balance').values('token_address', 'balance')
    tokens_with_balance = property(_tokens_with_balance)


class SafeCreation(TimeStampedModel):
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
        return 'Safe {} - Deployer {}'.format(self.safe, self.deployer)

    def wei_deploy_cost(self) -> int:
        """
        :return: int: Cost to deploy the contract in wei
        """
        return self.gas * self.gas_price


class SafeCreation2Manager(models.Manager):
    def pending_to_check(self):
        return self.exclude(
            tx_hash=None,
        ).filter(
            block_number=None,
        ).select_related(
            'safe'
        )

    def deployed_and_checked(self):
        return self.exclude(
            tx_hash=None,
            block_number=None,
        ).select_related(
            'safe'
        )


class SafeCreation2(TimeStampedModel):
    objects = SafeCreation2Manager()
    safe = models.OneToOneField(SafeContract, on_delete=models.CASCADE, primary_key=True)
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
            return 'Safe {} - Deployed on block number {}'.format(self.safe, self.block_number)
        else:
            return 'Safe {}'.format(self.safe)

    def deployed(self) -> bool:
        return self.block_number is not None

    def wei_estimated_deploy_cost(self) -> int:
        """
        :return: int: Cost to deploy the contract in wei
        """
        return self.gas_estimated * self.gas_price_estimated


class SafeFundingManager(models.Manager):
    def pending_just_to_deploy(self):
        return self.filter(
            safe_deployed=False
        ).filter(
            deployer_funded=True
        ).select_related(
            'safe'
        )

    def not_deployed(self):
        return self.filter(
            safe_deployed=False
        ).select_related(
            'safe'
        )


class SafeFunding(TimeStampedModel):
    objects = SafeFundingManager()
    safe = models.OneToOneField(SafeContract, primary_key=True, on_delete=models.CASCADE)
    safe_funded = models.BooleanField(default=False)
    deployer_funded = models.BooleanField(default=False, db_index=True)  # Set when deployer_funded_tx_hash is mined
    deployer_funded_tx_hash = Sha3HashField(unique=True, blank=True, null=True)
    safe_deployed = models.BooleanField(default=False, db_index=True)  # Set when safe_deployed_tx_hash is mined
    # We could use SafeCreation.tx_hash, but we would run into troubles because of Ganache
    safe_deployed_tx_hash = Sha3HashField(unique=True, blank=True, null=True)

    def is_all_funded(self):
        return self.safe_funded and self.deployer_funded

    def status(self):
        if self.safe_deployed:
            return 'DEPLOYED'
        elif self.safe_deployed_tx_hash:
            return 'DEPLOYED_UNCHECKED'
        elif self.deployer_funded:
            return 'DEPLOYER_FUNDED'
        elif self.deployer_funded_tx_hash:
            return 'DEPLOYER_FUNDED_UNCHECKED'
        elif self.safe_funded:
            return 'DEPLOYER_NOT_FUNDED_SAFE_WITH_BALANCE'
        else:
            return 'SAFE_WITHOUT_BALANCE'

    def __str__(self):
        s = 'Safe %s - ' % self.safe.address
        if self.safe_deployed:
            s += 'deployed'
        elif self.safe_deployed_tx_hash:
            s += 'deployed but not checked'
        elif self.deployer_funded:
            s += 'with deployer funded'
        elif self.deployer_funded_tx_hash:
            s += 'with deployer funded but not checked'
        elif self.safe_funded:
            s += 'has enough balance, but deployer is not funded yet'
        else:
            s = 'Safe %s' % self.safe.address
        return s


class EthereumTxManager(models.Manager):
    def create_from_tx(self, tx: Dict[str, any], tx_hash: bytes, block_number: Optional[int] = None):
        return super().create(
            tx_hash=tx_hash,
            block_number=block_number,
            _from=tx['from'],
            gas=tx['gas'],
            gas_price=tx['gasPrice'],
            data=HexBytes(tx['data']),
            nonce=tx['nonce'],
            to=tx.get('to'),
            value=tx['value'],
        )


class EthereumTx(models.Model):
    objects = EthereumTxManager()
    tx_hash = Sha3HashField(unique=True, primary_key=True)
    block_number = models.IntegerField(null=True, default=None)  # If mined
    gas_used = Uint256Field(null=True, default=None)  # If mined
    _from = EthereumAddressField(null=True, db_index=True)
    gas = Uint256Field()
    gas_price = Uint256Field()
    data = models.BinaryField(null=True)
    nonce = Uint256Field()
    to = EthereumAddressField(null=True, db_index=True)
    value = Uint256Field()

    def __str__(self):
        return '{} from={} to={}'.format(self.tx_hash, self._from, self.to)


class SafeMultisigTxManager(models.Manager):
    def get_last_nonce_for_safe(self, safe_address: str):
        tx = self.filter(safe=safe_address).order_by('-nonce').first()
        return tx.nonce if tx else None


class SafeMultisigTx(TimeStampedModel):
    objects = SafeMultisigTxManager()
    safe = models.ForeignKey(SafeContract, on_delete=models.CASCADE, related_name='multisig_txs')
    ethereum_tx = models.ForeignKey(EthereumTx, on_delete=models.CASCADE, related_name='multisig_txs')
    to = EthereumAddressField(null=True, db_index=True)
    value = Uint256Field()
    data = models.BinaryField(null=True)
    operation = models.PositiveSmallIntegerField(choices=[(tag.value, tag.name) for tag in SafeOperation])
    safe_tx_gas = Uint256Field()
    data_gas = Uint256Field()
    gas_price = Uint256Field()
    gas_token = EthereumAddressField(null=True)
    refund_receiver = EthereumAddressField(null=True)
    signatures = models.BinaryField()
    nonce = Uint256Field()
    safe_tx_hash = Sha3HashField(unique=True, null=True)

    class Meta:
        unique_together = (('safe', 'nonce'),)

    def __str__(self):
        return '{} - {} - Safe {}'.format(self.ethereum_tx.tx_hash, SafeOperation(self.operation).name,
                                          self.safe.address)


class InternalTxManager(models.Manager):
    def balance_for_all_safes(self):
        outgoing_balance = InternalTx.objects.filter(_from=OuterRef('to')).order_by().values('_from').annotate(
            total=Sum('value')).values('total')
        incoming_balance = InternalTx.objects.filter(to=OuterRef('to')).order_by().values('to').annotate(
            total=Sum('value')).values('total')
        return InternalTx.objects.annotate(balance=Subquery(incoming_balance, output_field=DecimalField()) -
                                                   Subquery(outgoing_balance,
                                                            output_field=DecimalField()))

    def calculate_balance(self, address: str) -> int:
        # balances_from = InternalTx.objects.filter(_from=safe_address).aggregate(value=Sum('value')).get('value', 0)
        # balances_to = InternalTx.objects.filter(to=safe_address).aggregate(value=Sum('value')).get('value', 0)
        # return balances_to - balances_from

        # If `from` we set `value` to `-value`, if `to` we let the `value` as it is. Then SQL `Sum` will get the balance
        return InternalTx.objects.filter(Q(_from=address) | Q(to=address)).annotate(
            balance=Case(
                When(_from=address, then=-F('value')),
                default='value',
            )
        ).aggregate(Sum('balance')).get('balance__sum', 0)


class InternalTx(models.Model):
    objects = InternalTxManager()
    ethereum_tx = models.ForeignKey(EthereumTx, on_delete=models.CASCADE, related_name='internal_txs')
    _from = EthereumAddressField(db_index=True)
    gas = Uint256Field()
    data = models.BinaryField(null=True)  # `input` for Call, `init` for Create
    to = EthereumAddressField(null=True, db_index=True)
    value = Uint256Field()
    gas_used = Uint256Field()
    contract_address = EthereumAddressField(null=True, db_index=True)  # Create
    code = models.BinaryField(null=True)                # Create
    output = models.BinaryField(null=True)              # Call
    call_type = models.PositiveSmallIntegerField(null=True,
                                                 choices=[(tag.value, tag.name) for tag in EthereumTxCallType])  # Call
    trace_address = models.CharField(max_length=100)  # Stringified traceAddress
    error = models.CharField(max_length=100, null=True)

    class Meta:
        unique_together = (('ethereum_tx', 'trace_address'),)

    def __str__(self):
        if self.to:
            return 'Internal tx hash={} from={} to={}'.format(self.ethereum_tx.tx_hash, self._from, self.to)
        else:
            return 'Internal tx hash={} from={}'.format(self.ethereum_tx.tx_hash, self._from)

    def tx_type(self) -> EthereumTxType:
        if self.contract_address:
            return EthereumTxType.CREATE
        else:
            return EthereumTxType.CALL


class SafeTxStatusManager(models.Manager):
    def deployed(self):
        return self.filter(safe__in=SafeContract.objects.deployed())


class SafeTxStatus(models.Model):
    """
    Have information about the last scan for internal txs
    """
    objects = SafeTxStatusManager()
    safe = models.OneToOneField(SafeContract, primary_key=True, on_delete=models.CASCADE)
    initial_block_number = models.IntegerField(default=0)  # Block number when Safe creation process was started
    tx_block_number = models.IntegerField(default=0)  # Block number when last internal tx scan ended
    erc_20_block_number = models.IntegerField(default=0)  # Block number when last erc20 events scan ended

    class Meta:
        verbose_name_plural = "Safe tx status"

    def __str__(self):
        return 'Safe {} - Initial-block-number={} - ' \
               'Tx-block-number={} - Erc20-block-number={}'.format(self.safe.address,
                                                                   self.initial_block_number,
                                                                   self.tx_block_number,
                                                                   self.erc_20_block_number)


class EthereumEventQuerySet(models.QuerySet):
    def not_erc_20_721_events(self):
        return self.exclude(topic=ERC20_721_TRANSFER_TOPIC)

    def erc20_721_events(self, token_address: Optional[str] = None, address: Optional[str] = None):
        queryset = self.filter(topic=ERC20_721_TRANSFER_TOPIC)
        if token_address:
            queryset = queryset.filter(token_address=token_address)
        if address:
            queryset = queryset.filter(Q(arguments__to=address) | Q(arguments__from=address))
        return queryset

    def erc20_events(self, token_address: Optional[str] = None, address: Optional[str] = None):
        return self.erc20_721_events(token_address=token_address,
                                     address=address).filter(arguments__has_key='value')

    def erc721_events(self, token_address: Optional[str] = None, address: Optional[str] = None):
        return self.erc20_721_events(token_address=token_address,
                                     address=address).filter(arguments__has_key='tokenId')

    def get_or_create_erc20_or_721_event(self, decoded_event: Dict[str, any]):
        if 'value' in decoded_event['args']:
            return self.get_or_create_erc20_event(decoded_event)
        elif 'tokenId' in decoded_event['args']:
            return self.get_or_create_erc20_event(decoded_event)
        raise ValueError('Invalid ERC20 or ERC721 event %s' % decoded_event)

    def get_or_create_erc20_event(self, decoded_event: Dict[str, any]):
        return self.get_or_create(ethereum_tx_id=decoded_event['transactionHash'],
                                  log_index=decoded_event['logIndex'],
                                  defaults={
                                      'token_address': decoded_event['address'],
                                      'topic': decoded_event['topics'][0],
                                      'arguments': {
                                          'from': decoded_event['args']['from'],
                                          'to': decoded_event['args']['to'],
                                          'value': decoded_event['args']['value'],
                                      }
                                  })

    def get_or_create_erc721_event(self, decoded_event: Dict[str, any]):
        return self.get_or_create(ethereum_tx_id=decoded_event['transactionHash'],
                                  log_index=decoded_event['logIndex'],
                                  defaults={
                                      'token_address': decoded_event.address,
                                      'topic': decoded_event['topics'][0],
                                      'arguments': {
                                          'from': decoded_event['args']['from'],
                                          'to': decoded_event['args']['to'],
                                          'tokenId': decoded_event['args']['tokenId'],
                                      }
                                  })


class EthereumEvent(models.Model):
    objects = EthereumEventQuerySet.as_manager()
    ethereum_tx = models.ForeignKey(EthereumTx, on_delete=models.CASCADE, related_name='events')
    log_index = models.PositiveIntegerField()
    token_address = EthereumAddressField(db_index=True)
    topic = Sha3HashField(db_index=True)
    arguments = JSONField()

    class Meta:
        unique_together = (('ethereum_tx', 'log_index'),)

    def __str__(self):
        return 'Tx-hash={} Log-index={} Arguments={}'.format(self.ethereum_tx_id, self.log_index, self.arguments)

    def is_erc20(self) -> bool:
        return 'value' in self.arguments

    def is_erc721(self) -> bool:
        return 'tokenId' in self.arguments
