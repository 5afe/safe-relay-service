import ethereum.utils
from django.contrib.postgres.fields import ArrayField
from django.db import models
from model_utils.models import TimeStampedModel

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

    def getBalance(self):
        pass

    def __str__(self):
        return self.address


class SafeCreation(TimeStampedModel):
    deployer = EthereumAddressField(primary_key=True)
    safe = models.OneToOneField(SafeContract, on_delete=models.CASCADE)
    owners = ArrayField(EthereumAddressField())
    threshold = models.PositiveSmallIntegerField()
    signed_tx = models.BinaryField()
    tx_hash = models.CharField(max_length=64, unique=True)
    gas = models.PositiveIntegerField()
    gas_price = models.BigIntegerField()
    v = models.PositiveSmallIntegerField()
    r = EthereumBigIntegerField()
    s = EthereumBigIntegerField()

    def sendEthToDeployer(self):
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
    deployer_funded_tx_hash = models.CharField(max_length=64, unique=True)
    safe_deployed = models.BooleanField(default=False, db_index=True)  # Set when safe_deployed_tx_hash is mined
    # We could use SafeCreation.tx_hash, but we would run into troubles because of Ganache
    safe_deployed_tx_hash = models.CharField(max_length=64, unique=True)

    def is_all_funded(self):
        return self.safe_funded and self.deployer_funded

    def __str__(self):
        s = 'Safe %s - ' % self.safe.address
        if self.safe_deployed:
            s += 'deployed'
        if self.safe_deployed_tx_hash:
            s += 'deployed but not checked'
        elif self.deployer_funded:
            s += 'with deployer funded'
        elif self.deployer_funded_tx_hash:
            s += 'with deployer funded but not checked'
        elif self.safe_funded:
            s += "has enough balance, but deployer is not funded yet"
        else:
            s = 'Safe %s' % self.safe.address
        return s
