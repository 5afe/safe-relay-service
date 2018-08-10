from typing import Dict, Iterable, List

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django_eth.models import (EthereumAddressField, EthereumBigIntegerField,
                               HexField, Uint256Field)
from model_utils.models import TimeStampedModel

from .ethereum_service import EthereumServiceProvider
from .safe_service import SafeServiceProvider


class SafeContract(TimeStampedModel):
    address = EthereumAddressField(primary_key=True)
    master_copy = EthereumAddressField()

    def has_valid_code(self) -> bool:
        return SafeServiceProvider().check_proxy_code(self.address)

    def has_valid_master_copy(self) -> bool:
        return SafeServiceProvider().check_master_copy(self.address)

    def get_balance(self, block_identifier=None):
        return EthereumServiceProvider().get_balance(address=self.address, block_identifier=block_identifier)

    def __str__(self):
        return self.address


class SafeCreationManager(models.Manager):
    def create_safe_tx(self, s: int, owners: Iterable[str], threshold: int):
        """
        Create models for safe tx
        :return:
        :rtype: SafeCreation
        """

        safe_service = SafeServiceProvider()
        safe_creation_tx = safe_service.build_safe_creation_tx(s, owners, threshold)

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
    threshold = Uint256Field()
    payment = Uint256Field()
    tx_hash = HexField(unique=True)
    gas = Uint256Field()
    gas_price = Uint256Field()
    value = Uint256Field()
    v = models.PositiveSmallIntegerField()
    r = EthereumBigIntegerField()
    s = EthereumBigIntegerField()
    data = models.BinaryField(null=True)
    signed_tx = models.BinaryField(null=True)

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
    deployer_funded_tx_hash = HexField(unique=True, blank=True, null=True)
    safe_deployed = models.BooleanField(default=False, db_index=True)  # Set when safe_deployed_tx_hash is mined
    # We could use SafeCreation.tx_hash, but we would run into troubles because of Ganache
    safe_deployed_tx_hash = HexField(unique=True, blank=True, null=True)

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
    class SafeMultisigTxExists(Exception):
        pass

    def create_multisig_tx(self,
                           safe_address: str,
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

        if self.filter(safe=safe_address, nonce=nonce).exists():
            raise self.SafeMultisigTxExists

        safe_service = SafeServiceProvider()

        signature_pairs = [(s['v'], s['r'], s['s']) for s in signatures]
        signatures_packed = safe_service.signatures_to_bytes(signature_pairs)

        tx_hash, tx = safe_service.send_multisig_tx(
            safe_address,
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

        safe_contract = SafeContract.objects.get(address=safe_address)

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
            tx_hash=tx_hash.hex(),
            tx_mined=False
        )


class SafeMultisigTx(TimeStampedModel):
    objects = SafeMultisigTxManager()
    safe = models.ForeignKey(SafeContract, on_delete=models.CASCADE)
    to = EthereumAddressField(null=True)
    value = Uint256Field()
    data = models.BinaryField(null=True)
    operation = models.PositiveSmallIntegerField()
    safe_tx_gas = Uint256Field()
    data_gas = Uint256Field()
    gas_price = Uint256Field()
    gas_token = EthereumAddressField(null=True)
    signatures = models.BinaryField()
    gas = Uint256Field()  # Gas for the tx that executes the multisig tx
    nonce = Uint256Field()
    tx_hash = HexField(unique=True)
    tx_mined = models.BooleanField(default=False)

    class Meta:
        unique_together = (('safe', 'nonce'),)
