from typing import Iterable

import ethereum.utils
from django.contrib.postgres.fields import ArrayField
from django.db import models
from model_utils.models import TimeStampedModel

from .ethereum_service import EthereumService
from .helpers import SafeCreationTxBuilder
from .validators import validate_checksumed_address


class EthereumAddressField(models.CharField):
    default_validators = [validate_checksumed_address]
    description = "Ethereum address"

    def __init__(self, *args, **kwargs):
        kwargs['max_length'] = 42
        super().__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        del kwargs['max_length']
        return name, path, args, kwargs

    def from_db_value(self, value, expression, connection):
        return self.to_python(value)

    def to_python(self, value):
        value = super().to_python(value)
        if not value:
            return value

        return ethereum.utils.checksum_encode(value)

    def get_prep_value(self, value):
        return ethereum.utils.checksum_encode(value)


class EthereumBigIntegerField(models.CharField):

    def __init__(self, *args, **kwargs):
        kwargs['max_length'] = 64
        super().__init__(*args, **kwargs)

    def from_db_value(self, value, expression, connection):
        return self.to_python(value)

    def to_python(self, value):
        value = super().to_python(value)
        if not value:
            return value
        else:
            return int(value, 16)

    def get_prep_value(self, value):
        if not value:
            return value
        if isinstance(value, str):
            return value
        else:
            return hex(int(value))[2:]


class SafeContract(TimeStampedModel):
    address = EthereumAddressField(primary_key=True)

    def getBalance(self, block_identifier=None):
        EthereumService().get_balance(address=self.address, block_identifier=block_identifier)

    def __str__(self):
        return self.address


class SafeCreationManager(models.Manager):
    def create_safe_tx(self, s: int, owners: Iterable[str], threshold: int):
        """
        Create models for safe tx
        :param s:
        :param owners:
        :param threshold:
        :return:
        """

        safe_creation_tx_builder = SafeCreationTxBuilder().get_safe_creation_tx(s, owners, threshold)

        safe_contract = SafeContract.objects.create(address=safe_creation_tx_builder.safe_address)
        return super().create(
            deployer=safe_creation_tx_builder.deployer_address,
            safe=safe_contract,
            owners=owners,
            threshold=threshold,
            payment=safe_creation_tx_builder.payment,
            tx_hash=safe_creation_tx_builder.tx_hash.hex(),
            gas=safe_creation_tx_builder.gas,
            gas_price=safe_creation_tx_builder.gas_price,
            value=safe_creation_tx_builder.contract_creation_tx.value,
            v=safe_creation_tx_builder.v,
            r=safe_creation_tx_builder.r,
            s=safe_creation_tx_builder.s,
            data=safe_creation_tx_builder.contract_creation_tx.data,
            signed_tx=safe_creation_tx_builder.raw_tx
        )


class SafeCreation(TimeStampedModel):
    objects = SafeCreationManager()
    deployer = EthereumAddressField(primary_key=True)
    safe = models.OneToOneField(SafeContract, on_delete=models.CASCADE)
    owners = ArrayField(EthereumAddressField())
    threshold = models.PositiveSmallIntegerField()
    payment = models.BigIntegerField()
    tx_hash = models.CharField(max_length=64, unique=True)
    gas = models.PositiveIntegerField()
    gas_price = models.BigIntegerField()
    value = models.BigIntegerField()
    v = models.PositiveSmallIntegerField()
    r = EthereumBigIntegerField()
    s = EthereumBigIntegerField()
    data = models.BinaryField(null=True)
    signed_tx = models.BinaryField(null=True)

    def send_eth_to_deployer(self):
        pass

    def __str__(self):
        return 'Deployer {} - Safe {}'.format(self.deployer, self.safe)


class SafeFundingManager(models.Manager):
    def pending_to_deploy(self):
        return self.filter(
            safe_deployed=False
        ).filter(
            deployer_funded=True
        ).select_related(
            'safe'
        )


class SafeFunding(TimeStampedModel):
    objects = SafeFundingManager()
    safe = models.OneToOneField(SafeContract, primary_key=True, on_delete=models.CASCADE)
    safe_funded = models.BooleanField(default=False)
    deployer_funded = models.BooleanField(default=False, db_index=True)  # Set when deployer_funded_tx_hash is mined
    deployer_funded_tx_hash = models.CharField(max_length=64, unique=True, blank=True, null=True)
    safe_deployed = models.BooleanField(default=False, db_index=True)  # Set when safe_deployed_tx_hash is mined
    # We could use SafeCreation.tx_hash, but we would run into troubles because of Ganache
    safe_deployed_tx_hash = models.CharField(max_length=64, unique=True, blank=True, null=True)

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
            s = 'Safe %s' % self.safe.address
        return s

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
