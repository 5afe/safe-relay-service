import datetime
from decimal import Decimal
from enum import Enum
from typing import Dict, List, Optional

from django.contrib.postgres.fields import ArrayField, JSONField
from django.db import connection, models
from django.db.models import (Avg, Case, Count, DurationField, F, Q, Sum,
                              Value, When)
from django.db.models.expressions import OuterRef, RawSQL, Subquery, Window
from django.db.models.functions import Cast, Coalesce, TruncDate

from hexbytes import HexBytes
from model_utils.models import TimeStampedModel

from gnosis.eth.constants import ERC20_721_TRANSFER_TOPIC
from gnosis.eth.django.models import (EthereumAddressField, Sha3HashField,
                                      Uint256Field)
from gnosis.safe import SafeOperation


def parse_row(row):
    """
    Remove Decimal from Raw SQL queries
    """
    for r in row:
        if isinstance(r, Decimal):
            if r.as_integer_ratio()[1] == 1:
                yield int(r)
            else:
                yield float(r)
        else:
            yield r


def run_raw_query(query: str, *arguments):
    with connection.cursor() as cursor:
        cursor.execute(query, arguments)
        columns = [col[0] for col in cursor.description]
        return [
            dict(zip(columns, parse_row(row)))
            for row in cursor.fetchall()
        ]


class EthereumTxType(Enum):
    CALL = 0
    CREATE = 1
    SELF_DESTRUCT = 2

    @staticmethod
    def parse(tx_type: str):
        tx_type = tx_type.upper()
        if tx_type == 'CALL':
            return EthereumTxType.CALL
        elif tx_type == 'CREATE':
            return EthereumTxType.CREATE
        elif tx_type == 'SUICIDE':
            return EthereumTxType.SELF_DESTRUCT
        else:
            raise ValueError('%s is not a valid EthereumTxType' % tx_type)


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


class SafeContractManager(models.Manager):
    def get_average_deploy_time(self, from_date: datetime.datetime, to_date: datetime.datetime) -> datetime.timedelta:
        query = """
        SELECT AVG(EB.timestamp - SC.created)
        FROM (SELECT created, tx_hash FROM relay_safecreation
              UNION SELECT created, tx_hash FROM relay_safecreation2) AS SC
        JOIN relay_ethereumtx as ET ON SC.tx_hash=ET.tx_hash JOIN relay_ethereumblock as EB ON ET.block_id=EB.number
        WHERE SC.created BETWEEN %s AND %s
        """
        with connection.cursor() as cursor:
            cursor.execute(query, [from_date, to_date])
            return cursor.fetchone()[0]

    def get_average_deploy_time_grouped(self, from_date: datetime.datetime, to_date: datetime.datetime) -> datetime.timedelta:
        query = """
        SELECT DATE(SC.created) as created_date, AVG(EB.timestamp - SC.created) as average_deploy_time
        FROM (SELECT created, tx_hash FROM relay_safecreation
              UNION SELECT created, tx_hash FROM relay_safecreation2) AS SC
        JOIN relay_ethereumtx as ET ON SC.tx_hash=ET.tx_hash JOIN relay_ethereumblock as EB ON ET.block_id=EB.number
        WHERE SC.created BETWEEN %s AND %s
        GROUP BY DATE(SC.created)
        """

        return run_raw_query(query, from_date, to_date)

    def get_total_balance(self, from_date: datetime.datetime, to_date: datetime.datetime) -> int:
        return int(self.with_balance().filter(
            created__range=(from_date, to_date)
        ).aggregate(total_balance=Sum('balance')).get('total_balance') or 0)

    def get_total_token_balance(self, from_date: datetime.datetime, to_date: datetime.datetime) -> Dict[str, any]:
        """
        :return: Dictionary of {token_address: str, balance: decimal}
        """
        query = """
                SELECT token_address, SUM(EE.value) as balance FROM
                  (SELECT SC.created, ethereum_tx_id, address, token_address, -(arguments->>'value')::decimal AS value
                   FROM relay_safecontract SC JOIN relay_ethereumevent EV
                   ON SC.address = EV.arguments->>'from'
                   WHERE arguments ? 'value' AND topic='{0}'
                   UNION SELECT SC.created, ethereum_tx_id, address, token_address, (arguments->>'value')::decimal
                   FROM relay_safecontract SC JOIN relay_ethereumevent EV
                   ON SC.address = EV.arguments->>'to'
                   WHERE arguments ? 'value' AND topic='{0}') AS EE
                WHERE EE.created BETWEEN %s AND %s
                GROUP BY token_address
                """.format(ERC20_721_TRANSFER_TOPIC.replace('0x', ''))  # No risk of SQL Injection

        return run_raw_query(query, from_date, to_date)

    def get_total_volume(self, from_date: datetime.datetime, to_date: datetime.datetime) -> int:
        query = """
        SELECT SUM(IT.value) AS value
        FROM relay_safecontract SC
        JOIN relay_internaltx IT ON SC.address=IT."_from" OR SC.address=IT."to"
        JOIN relay_ethereumtx ET ON IT.ethereum_tx_id=ET.tx_hash
        JOIN relay_ethereumblock EB ON ET.block_id=EB.number
        WHERE IT.call_type != {0}
              AND error IS NULL
              AND EB.timestamp BETWEEN %s AND %s
        """.format(EthereumTxCallType.DELEGATE_CALL.value)
        with connection.cursor() as cursor:
            cursor.execute(query, [from_date, to_date])
            value = cursor.fetchone()[0]
            if value is not None:
                return int(value)

    def get_total_volume_grouped(self, from_date: datetime.datetime, to_date: datetime.datetime) -> int:
        query = """
        SELECT DATE(EB.timestamp) as date,
               SUM(IT.value) AS value
        FROM relay_safecontract SC
        JOIN relay_internaltx IT ON SC.address=IT."_from" OR SC.address=IT."to"
        JOIN relay_ethereumtx ET ON IT.ethereum_tx_id=ET.tx_hash
        JOIN relay_ethereumblock EB ON ET.block_id=EB.number
        WHERE IT.call_type != {0}
              AND error IS NULL
              AND EB.timestamp BETWEEN %s AND %s
        GROUP BY DATE(EB.timestamp)
        ORDER BY DATE(EB.timestamp)
        """.format(EthereumTxCallType.DELEGATE_CALL.value)

        return run_raw_query(query, from_date, to_date)

    def get_total_token_volume(self, from_date: datetime.datetime, to_date: datetime.datetime):
        """
        :return: Dictionary of {token_address: str, volume: int}
        """
        query = """
        SELECT EV.token_address, SUM((EV.arguments->>'value')::decimal) AS value
        FROM relay_safecontract SC
        JOIN relay_ethereumevent EV ON SC.address = EV.arguments->>'from' OR SC.address = EV.arguments->>'to'
        JOIN relay_ethereumtx ET ON EV.ethereum_tx_id=ET.tx_hash
        JOIN relay_ethereumblock EB ON ET.block_id=EB.number
        WHERE arguments ? 'value'
              AND topic='{0}'
              AND EB.timestamp BETWEEN %s AND %s
        GROUP BY token_address""".format(ERC20_721_TRANSFER_TOPIC.replace('0x', ''))  # No risk of SQL Injection

        return run_raw_query(query, from_date, to_date)

    def get_total_token_volume_grouped(self, from_date: datetime.datetime, to_date: datetime.datetime):
        """
        :return: Dictionary of {token_address: str, volume: int}
        """
        query = """
        SELECT DATE(EB.timestamp) as date, EV.token_address, SUM((EV.arguments->>'value')::decimal) AS value
        FROM relay_safecontract SC
        JOIN relay_ethereumevent EV ON SC.address = EV.arguments->>'from' OR SC.address = EV.arguments->>'to'
        JOIN relay_ethereumtx ET ON EV.ethereum_tx_id=ET.tx_hash
        JOIN relay_ethereumblock EB ON ET.block_id=EB.number
        WHERE arguments ? 'value'
              AND topic='{0}'
              AND EB.timestamp BETWEEN %s AND %s
        GROUP BY DATE(EB.timestamp), token_address
        ORDER BY DATE(EB.timestamp)""".format(ERC20_721_TRANSFER_TOPIC.replace('0x', ''))  # No risk of SQL Injection

        return run_raw_query(query, from_date, to_date)

    def get_creation_tokens_usage(self, from_date: datetime.datetime,
                                  to_date: datetime.datetime) -> Optional[List[Dict[str, any]]]:
        query = """
        SELECT DISTINCT payment_token, COUNT(*) OVER(PARTITION BY payment_token) as number,
                        100.0 * COUNT(*) OVER(PARTITION BY payment_token) / COUNT(*) OVER() as percentage
        FROM (SELECT tx_hash, payment_token, created FROM relay_safecreation
              UNION SELECT tx_hash, payment_token, created FROM relay_safecreation2) SC
        JOIN relay_ethereumtx ET ON SC.tx_hash = ET.tx_hash
        WHERE SC.created BETWEEN %s AND %s
        """

        return run_raw_query(query, from_date, to_date)

    def get_creation_tokens_usage_grouped(self, from_date: datetime.datetime,
                                          to_date: datetime.datetime) -> Optional[List[Dict[str, any]]]:
        query = """
        SELECT DISTINCT DATE(SC.created), payment_token,
                        COUNT(*) OVER(PARTITION BY DATE(SC.created), payment_token) as number,
                        100.0 * COUNT(*) OVER(PARTITION BY DATE(SC.created), payment_token) /
                                COUNT(*) OVER(PARTITION BY DATE(SC.created)) as percentage
        FROM (SELECT tx_hash, payment_token, created FROM relay_safecreation
              UNION SELECT tx_hash, payment_token, created FROM relay_safecreation2) SC
        JOIN relay_ethereumtx ET ON SC.tx_hash = ET.tx_hash
        WHERE SC.created BETWEEN %s AND %s
        ORDER BY(DATE(SC.created))
        """
        # Returns list of {'date': date, 'payment_token': Optional[str], 'number': int, percentage: 'float')
        return run_raw_query(query, from_date, to_date)


class SafeContractQuerySet(models.QuerySet):
    def with_balance(self):
        """
        :return: Queryset with the Safes and a `balance` attribute
        """
        return self.annotate(
            balance=Subquery(
                InternalTx.objects.balance_for_all_safes(
                ).filter(
                    to=OuterRef('address')
                ).values('balance').distinct(),
                models.DecimalField()))

    def with_token_balance(self):
        """
        :return: Dictionary of {address: str, token_address: str and balance: int}
        """
        query = """
        SELECT address, token_address, SUM(value) as balance FROM
          (SELECT address, token_address, -(arguments->>'value')::decimal AS value
           FROM relay_safecontract JOIN relay_ethereumevent
           ON relay_safecontract.address = relay_ethereumevent.arguments->>'from'
           WHERE arguments ? 'value' AND topic='{0}'
           UNION SELECT address, token_address, (arguments->>'value')::decimal
           FROM relay_safecontract JOIN relay_ethereumevent
           ON relay_safecontract.address = relay_ethereumevent.arguments->>'to'
           WHERE arguments ? 'value' AND topic='{0}') AS X
        GROUP BY address, token_address
        """.format(ERC20_721_TRANSFER_TOPIC.replace('0x', ''))

        return run_raw_query(query)

    def deployed(self):
        return self.filter(
            ~Q(safecreation2__block_number=None) | Q(safefunding__safe_deployed=True)
        )

    def not_deployed(self):
        return self.exclude(
            ~Q(safecreation2__block_number=None) | Q(safefunding__safe_deployed=True)
        )


class SafeContract(TimeStampedModel):
    objects = SafeContractManager.from_queryset(SafeContractQuerySet)()
    address = EthereumAddressField(primary_key=True)
    master_copy = EthereumAddressField()

    def __str__(self):
        return 'Safe=%s Master-copy=%s' % (self.address, self.master_copy)

    def get_balance(self) -> int:
        return InternalTx.objects.calculate_balance(self.address)

    def get_tokens_with_balance(self) -> List[Dict[str, any]]:
        return EthereumEvent.objects.erc20_tokens_with_balance(self.address)


class SafeCreationManager(models.Manager):
    def get_tokens_usage(self) -> Optional[List[Dict[str, any]]]:
        """
        :return: List of Dict 'gas_token', 'total', 'number', 'percentage'
        """
        total = self.deployed_and_checked().annotate(_x=Value(1)).values('_x').annotate(total=Count('_x')
                                                                                        ).values('total')
        return self.deployed_and_checked().values('payment_token').annotate(
            total=Subquery(total, output_field=models.IntegerField())
        ).annotate(
            number=Count('safe_id'), percentage=Cast(100.0 * Count('pk') / F('total'),
                                                     models.FloatField()))


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
        return 'Safe {} - Deployer {}'.format(self.safe, self.deployer)

    def wei_deploy_cost(self) -> int:
        """
        :return: int: Cost to deploy the contract in wei
        """
        return self.gas * self.gas_price


class SafeCreation2Manager(models.Manager):
    def get_tokens_usage(self) -> Optional[List[Dict[str, any]]]:
        """
        :return: List of Dict 'gas_token', 'total', 'number', 'percentage'
        """
        total = self.deployed_and_checked().annotate(_x=Value(1)).values('_x').annotate(total=Count('_x')
                                                                                        ).values('total')
        return self.deployed_and_checked().values('payment_token').annotate(
            total=Subquery(total, output_field=models.IntegerField())
        ).annotate(
            number=Count('safe_id'), percentage=Cast(100.0 * Count('pk') / F('total'),
                                                     models.FloatField()))


class SafeCreation2QuerySet(models.QuerySet):
    def deployed_and_checked(self):
        return self.exclude(
            tx_hash=None,
            block_number=None,
        ).select_related(
            'safe'
        )

    def not_deployed(self):
        return self.filter(tx_hash=None)

    def pending_to_check(self):
        return self.exclude(
            tx_hash=None,
        ).filter(
            block_number=None,
        ).select_related(
            'safe'
        )


class SafeCreation2(TimeStampedModel):
    objects = SafeCreation2Manager.from_queryset(SafeCreation2QuerySet)()
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


class SafeFundingQuerySet(models.QuerySet):
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
    objects = SafeFundingQuerySet.as_manager()
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


class EthereumBlockManager(models.Manager):
    def create_from_block(self, block: Dict[str, any]) -> 'EthereumBlock':
        return super().create(
            number=block['number'],
            gas_limit=block['gasLimit'],
            gas_used=block['gasUsed'],
            timestamp=datetime.datetime.fromtimestamp(block['timestamp'], datetime.timezone.utc),
            block_hash=block['hash'],
        )


class EthereumBlock(models.Model):
    objects = EthereumBlockManager()
    number = models.PositiveIntegerField(primary_key=True, unique=True)
    gas_limit = models.PositiveIntegerField()
    gas_used = models.PositiveIntegerField()
    timestamp = models.DateTimeField()
    block_hash = Sha3HashField(unique=True)


class EthereumTxManager(models.Manager):
    def create_from_tx(self, tx: Dict[str, any], tx_hash: bytes, gas_used: Optional[int] = None,
                       ethereum_block: Optional[EthereumBlock] = None):
        return super().create(
            block=ethereum_block,
            tx_hash=tx_hash,
            _from=tx['from'],
            gas=tx['gas'],
            gas_price=tx['gasPrice'],
            gas_used=gas_used,
            data=HexBytes(tx.get('data') or tx.get('input')),
            nonce=tx['nonce'],
            to=tx.get('to'),
            value=tx['value'],
        )


class EthereumTx(TimeStampedModel):
    objects = EthereumTxManager()
    block = models.ForeignKey(EthereumBlock, on_delete=models.CASCADE, null=True, default=None,
                              related_name='txs')  # If mined
    tx_hash = Sha3HashField(unique=True, primary_key=True)
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
    def get_last_nonce_for_safe(self, safe_address: str) -> Optional[int]:
        nonce_dict = self.filter(safe=safe_address).order_by('-nonce').values('nonce').first()
        return nonce_dict['nonce'] if nonce_dict else None

    def get_average_execution_time(self, from_date: datetime.datetime,
                                   to_date: datetime.datetime) -> Optional[datetime.timedelta]:
        return self.select_related(
            'ethereum_tx', 'ethereum_tx__block'
        ).exclude(
            ethereum_tx__block=None,
        ).annotate(
            interval=Cast(F('ethereum_tx__block__timestamp') - F('created'),
                          output_field=DurationField())
        ).filter(
            created__range=(from_date, to_date)
        ).aggregate(median=Avg('interval'))['median']

    def get_average_execution_time_grouped(self, from_date: datetime.datetime,
                                           to_date: datetime.datetime) -> Optional[datetime.timedelta]:
        return self.select_related(
            'ethereum_tx', 'ethereum_tx__block'
        ).exclude(
            ethereum_tx__block=None,
        ).annotate(
            interval=Cast(F('ethereum_tx__block__timestamp') - F('created'),
                          output_field=DurationField())
        ).filter(
            created__range=(from_date, to_date)
        ).annotate(
            created_date=TruncDate('created')
        ).values(
            'created_date'
        ).annotate(
            median=Avg('interval')
        ).values('created_date', 'median')

    def get_tokens_usage(self) -> Optional[List[Dict[str, any]]]:
        """
        :return: List of Dict 'gas_token', 'total', 'number', 'percentage'
        """
        total = self.annotate(_x=Value(1)).values('_x').annotate(total=Count('_x')).values('total')
        return self.values(
            'gas_token'
        ).annotate(
            total=Subquery(total, output_field=models.IntegerField())
        ).annotate(
            number=Count('pk'), percentage=Cast(100.0 * Count('pk') / F('total'), models.FloatField())
        )

    def get_tokens_usage_grouped(self) -> Optional[List[Dict[str, any]]]:
        """
        :return: List of Dict 'gas_token', 'total', 'number', 'percentage'
        """
        return SafeMultisigTx.objects.annotate(
            date=TruncDate('created')
        ).annotate(
            number=Window(expression=Count('*'),
                          partition_by=[F('gas_token'), F('date')]),
            percentage=100.0 * Window(expression=Count('*'),
                                      partition_by=[F('gas_token'),
                                                    F('date')]
                                      ) / Window(expression=Count('*'),
                                                 partition_by=[F('date')])
        ).values(
            'date', 'gas_token', 'number', 'percentage'
        ).distinct().order_by('date')


class SafeMultisigTxQuerySet(models.QuerySet):
    def pending(self):
        return self.filter(ethereum_tx__block=None)


class SafeMultisigTx(TimeStampedModel):
    objects = SafeMultisigTxManager.from_queryset(SafeMultisigTxQuerySet)()
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
        # Exclude `DELEGATE_CALL` and errored transactions from `balance` calculations

        # There must be at least 2 txs (one in and another out for this method to work
        # SELECT SUM(value) FROM "relay_internaltx" U0 WHERE U0."_from" = address
        # sum
        # -----
        # (1 row)

        # But Django uses group by
        # SELECT SUM(value) FROM "relay_internaltx" U0 WHERE U0."_from" = '0xE3726b0a9d59c3B28947Ae450e8B8FC864c7f77f' GROUP BY U0."_from"
        # sum
        # -----
        # (0 rows)

        # We would like to translate this query into Django (excluding errors and DELEGATE_CALLs),
        # but it's not working as Django always try to `GROUP BY` when using `annotate`
        # SELECT *, (SELECT SUM(CASE WHEN "to"=R.to THEN value ELSE -value END)
        # FROM relay_internaltx
        # WHERE "to"=R.to OR _from=R.to) FROM relay_internaltx R;

        outgoing_balance = self.filter(
            _from=OuterRef('to'), error=None
        ).exclude(
            call_type=EthereumTxCallType.DELEGATE_CALL.value
        ).order_by().values('_from').annotate(
            total=Coalesce(Sum('value'), 0)
        ).values('total')

        incoming_balance = self.filter(
            to=OuterRef('to'), error=None
        ).exclude(
            call_type=EthereumTxCallType.DELEGATE_CALL.value
        ).order_by().values('to').annotate(
            total=Coalesce(Sum('value'), 0)
        ).values('total')

        return self.annotate(balance=Subquery(incoming_balance, output_field=models.DecimalField()) -
                                     Subquery(outgoing_balance, output_field=models.DecimalField()))

    def calculate_balance(self, address: str) -> int:
        # balances_from = InternalTx.objects.filter(_from=safe_address).aggregate(value=Sum('value')).get('value', 0)
        # balances_to = InternalTx.objects.filter(to=safe_address).aggregate(value=Sum('value')).get('value', 0)
        # return balances_to - balances_from

        # If `from` we set `value` to `-value`, if `to` we let the `value` as it is. Then SQL `Sum` will get the balance
        # balance = InternalTx.objects.filter(
        #     error=None  # Exclude errored txs
        # ).exclude(
        #     call_type=EthereumTxCallType.DELEGATE_CALL.value  # Exclude delegate calls
        # ).exclude(
        #     Q(_from=address) & Q(to=address)  # Exclude txs to the same address
        # ).filter(
        #     Q(_from=address) | Q(to=address)
        # ).annotate(
        #     balance=Case(
        #         When(_from=address, then=-F('value')),
        #         default='value',
        #     )
        # ).aggregate(Sum('balance')).get('balance__sum', 0)
        # return balance if balance else 0
        internal_tx = self.balance_for_all_safes().filter(to=address).values('balance').first()
        if not internal_tx:
            return 0
        else:
            return int(internal_tx.get('balance') or 0)


class InternalTx(models.Model):
    objects = InternalTxManager()
    ethereum_tx = models.ForeignKey(EthereumTx, on_delete=models.CASCADE, related_name='internal_txs')
    _from = EthereumAddressField(null=True, db_index=True)  # For SELF-DESTRUCT it can be null
    gas = Uint256Field()
    data = models.BinaryField(null=True)  # `input` for Call, `init` for Create
    to = EthereumAddressField(null=True, db_index=True)
    value = Uint256Field()
    gas_used = Uint256Field()
    contract_address = EthereumAddressField(null=True, db_index=True)  # Create
    code = models.BinaryField(null=True)                # Create
    output = models.BinaryField(null=True)              # Call
    refund_address = EthereumAddressField(null=True, db_index=True)  # For SELF-DESTRUCT
    tx_type = models.PositiveSmallIntegerField(choices=[(tag.value, tag.name) for tag in EthereumTxType])
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


class SafeTxStatusQuerySet(models.QuerySet):
    def deployed(self):
        return self.filter(safe__in=SafeContract.objects.deployed())


class SafeTxStatus(models.Model):
    """
    Have information about the last scan for internal txs
    """
    objects = SafeTxStatusQuerySet.as_manager()
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

    def erc20_and_721_events(self, token_address: Optional[str] = None, address: Optional[str] = None):
        queryset = self.filter(topic=ERC20_721_TRANSFER_TOPIC)
        if token_address:
            queryset = queryset.filter(token_address=token_address)
        if address:
            queryset = queryset.filter(Q(arguments__to=address) | Q(arguments__from=address))
        return queryset

    def erc20_events(self, token_address: Optional[str] = None, address: Optional[str] = None):
        return self.erc20_and_721_events(token_address=token_address,
                                         address=address).filter(arguments__has_key='value')

    def erc721_events(self, token_address: Optional[str] = None, address: Optional[str] = None):
        return self.erc20_and_721_events(token_address=token_address,
                                         address=address).filter(arguments__has_key='tokenId')


class EthereumEventManager(models.Manager):
    def erc20_tokens_with_balance(self, address: str) -> List[Dict[str, any]]:
        """
        :return: List of dictionaries {'token_address': str, 'balance': int}
        """
        arguments_value_field = RawSQL("(arguments->>'value')::numeric", ())
        return self.erc20_events(
            address=address
        ).values('token_address').annotate(
            balance=Sum(Case(
                When(arguments__from=address, then=-arguments_value_field),
                default=arguments_value_field,
            ))
        ).order_by('-balance').values('token_address', 'balance')

    def get_or_create_erc20_or_721_event(self, decoded_event: Dict[str, any]):
        if 'value' in decoded_event['args']:
            return self.get_or_create_erc20_event(decoded_event)
        elif 'tokenId' in decoded_event['args']:
            return self.get_or_create_erc721_event(decoded_event)
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
                                      'token_address': decoded_event['address'],
                                      'topic': decoded_event['topics'][0],
                                      'arguments': {
                                          'from': decoded_event['args']['from'],
                                          'to': decoded_event['args']['to'],
                                          'tokenId': decoded_event['args']['tokenId'],
                                      }
                                  })


class EthereumEvent(models.Model):
    objects = EthereumEventManager.from_queryset(EthereumEventQuerySet)()
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
