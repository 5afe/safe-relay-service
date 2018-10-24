from typing import Dict, Iterable, List

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django_eth.models import EthereumAddressField, Sha3HashField, Uint256Field
from gnosis.safe.ethereum_service import EthereumServiceProvider
from gnosis.safe.safe_service import (InvalidMultisigTx, SafeOperation,
                                      SafeServiceProvider)
from model_utils.models import TimeStampedModel

from safe_relay_service.gas_station.gas_station import GasStationProvider


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
        gas_station = GasStationProvider()
        fast_gas_price: int = gas_station.get_gas_prices().fast
        safe_creation_tx = safe_service.build_safe_creation_tx(s, owners, threshold, fast_gas_price)

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
    tx_hash = Sha3HashField(unique=True)
    gas = Uint256Field()
    gas_price = Uint256Field()
    value = Uint256Field()
    v = models.PositiveSmallIntegerField()
    r = Uint256Field()
    s = Uint256Field()
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


class SafeMultisigTxManager(models.Manager):
    class SafeMultisigTxExists(Exception):
        pass

    class SafeMultisigTxError(Exception):
        pass

    def get_last_nonce_for_safe(self, safe_address: str):
        tx = self.filter(safe=safe_address).order_by('-nonce').first()
        return tx.nonce if tx else None

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
                           refund_receiver: str,
                           nonce: int,
                           signatures: List[Dict[str, int]]):
        """
        :return: Database model of SafeMultisigTx
        :raises: SafeMultisigTxExists: If Safe Multisig Tx with nonce already exists
        :raises: SafeMultisigTxError: If Safe Tx is not valid (not sorted owners, bad signature, bad nonce...)
        """

        if self.filter(safe=safe_address, nonce=nonce).exists():
            raise self.SafeMultisigTxExists

        safe_service = SafeServiceProvider()

        signature_pairs = [(s['v'], s['r'], s['s']) for s in signatures]
        signatures_packed = safe_service.signatures_to_bytes(signature_pairs)

        try:
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
                refund_receiver,
                signatures_packed,
            )
        except InvalidMultisigTx as exc:
            raise self.SafeMultisigTxError(str(exc)) from exc

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
            refund_receiver=refund_receiver,
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
    operation = models.PositiveSmallIntegerField(choices=[(tag.value, tag.name) for tag in SafeOperation])
    safe_tx_gas = Uint256Field()
    data_gas = Uint256Field()
    gas_price = Uint256Field()
    gas_token = EthereumAddressField(null=True)
    refund_receiver = EthereumAddressField(null=True)
    signatures = models.BinaryField()
    gas = Uint256Field()  # Gas for the tx that executes the multisig tx
    nonce = Uint256Field()
    tx_hash = Sha3HashField(unique=True)
    tx_mined = models.BooleanField(default=False)

    class Meta:
        unique_together = (('safe', 'nonce'),)

    def __str__(self):
        return '{} - {} - Safe {}'.format(self.tx_hash, SafeOperation(self.operation).name, self.safe.address)
