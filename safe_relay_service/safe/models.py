from typing import Dict, Iterable, List, Tuple

import ethereum.utils
from django.contrib.postgres.fields import ArrayField
from django.db import models
from model_utils.models import TimeStampedModel

from .ethereum_service import EthereumServiceProvider
from .safe_service import SafeServiceProvider
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
        if value:
            return ethereum.utils.checksum_encode(value)
        else:
            return value

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value:
            return ethereum.utils.checksum_encode(value)
        else:
            return value


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
    master_copy = EthereumAddressField()

    def getBalance(self, block_identifier=None):
        EthereumServiceProvider().get_balance(address=self.address, block_identifier=block_identifier)

    def __str__(self):
        return self.address


class SafeCreationManager(models.Manager):
    def create_safe_tx(self, s: int, owners: Iterable[str], threshold: int, master_copy: str=None):
        """
        Create models for safe tx
        :return:
        :rtype: SafeCreation
        """

        safe_service = SafeServiceProvider()
        safe_creation_tx = safe_service.build_safe_creation_tx(s, owners, threshold, master_copy=master_copy)

        safe_contract = SafeContract.objects.create(address=safe_creation_tx.safe_address,
                                                    master_copy=safe_creation_tx.master_copy)
        return super().create(
            deployer=safe_creation_tx.deployer_address,
            safe=safe_contract,
            owners=owners,
            threshold=threshold,
            payment=safe_creation_tx.payment,
            tx_hash=safe_creation_tx.tx_hash.hex(),
            gas=safe_creation_tx.gas,
            gas_price=safe_creation_tx.gas_price,
            value=safe_creation_tx.contract_creation_tx.value,
            v=safe_creation_tx.v,
            r=safe_creation_tx.r,
            s=safe_creation_tx.s,
            data=safe_creation_tx.contract_creation_tx.data,
            signed_tx=safe_creation_tx.raw_tx
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


class SafeMultisigTxManager(models.Manager):
    def create_multisig_tx(self,
                           safe: str,
                           to: str,
                           value: int,
                           data: bytes,
                           operation: int,
                           safe_tx_gas: int,
                           data_gas: int,
                           gas_price: int,
                           gas_token: str,
                           nonce: int,
                           signatures: List[Dict[str, int]]):

        safe_service = SafeServiceProvider()

        signature_pairs = [(s['v'], s['r'], s['s']) for s in signatures]
        signatures_packed = safe_service.signatures_to_bytes(signature_pairs)

        tx_hash, tx = safe_service.send_multisig_tx(
            safe,
            to,
            value,
            data,
            operation,
            safe_tx_gas,
            data_gas,
            gas_price,
            gas_token,
            signatures_packed,
        )

        safe_contract = SafeContract.objects.get(address=safe)

        return super().create(
            safe=safe_contract,
            to=to,
            value=value,
            data=data,
            operation=operation,
            safe_tx_gas=safe_tx_gas,
            data_gas=data_gas,
            gas_price=gas_price,
            gas_token=gas_token,
            nonce=nonce,
            signatures=signatures_packed,
            gas=tx['gas'],
            tx_hash=tx_hash.hex()[2:],
            tx_mined=False
        )


class SafeMultisigTx(TimeStampedModel):
    objects = SafeMultisigTxManager()
    safe = models.ForeignKey(SafeContract, on_delete=models.CASCADE)
    to = EthereumAddressField(null=True)
    value = models.BigIntegerField()
    data = models.BinaryField(null=True)
    operation = models.PositiveSmallIntegerField()
    safe_tx_gas = models.PositiveIntegerField()
    data_gas = models.PositiveIntegerField()
    gas_price = models.BigIntegerField()
    gas_token = EthereumAddressField(null=True)
    signatures = models.BinaryField()
    gas = models.PositiveIntegerField()  # Gas for the tx that executes the multisig tx
    nonce = models.PositiveIntegerField()
    tx_hash = models.CharField(max_length=64, unique=True)
    tx_mined = models.BooleanField(default=False)
