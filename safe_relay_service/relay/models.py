from django.contrib.postgres.fields import ArrayField
from django.db import models

from model_utils.models import TimeStampedModel

from gnosis.eth import EthereumServiceProvider
from gnosis.eth.django.models import (EthereumAddressField, Sha3HashField,
                                      Uint256Field)
from gnosis.safe.safe_service import SafeOperation, SafeServiceProvider


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

    def __str__(self):
        return 'Safe {} - Deployer {}'.format(self.safe, self.deployer)

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


class SafeMultisigTxManager(models.Manager):
    def get_last_nonce_for_safe(self, safe_address: str):
        tx = self.filter(safe=safe_address).order_by('-nonce').first()
        return tx.nonce if tx else None


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
    safe_tx_hash = Sha3HashField(unique=True, null=True)
    tx_hash = Sha3HashField(unique=True)
    tx_mined = models.BooleanField(default=False)

    class Meta:
        unique_together = (('safe', 'nonce'),)

    def __str__(self):
        return '{} - {} - Safe {}'.format(self.tx_hash, SafeOperation(self.operation).name, self.safe.address)
