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
        """
        Remove 0x to store in the DB
        """
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


class SafeCreation(TimeStampedModel):
    deployer = EthereumAddressField(primary_key=True)
    owners = ArrayField(EthereumAddressField())
    threshold = models.PositiveSmallIntegerField()
    safe = models.ForeignKey(SafeContract, on_delete=models.CASCADE)
    signed_tx = models.BinaryField()
    tx_hash = models.CharField(max_length=64, unique=True)
    gas = models.PositiveIntegerField()
    gas_price = models.BigIntegerField()
    v = models.PositiveSmallIntegerField()
    r = EthereumBigIntegerField()
    s = EthereumBigIntegerField()

    def sendEthToDeployer(self):
        pass
