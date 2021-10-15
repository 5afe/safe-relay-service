from django.core.exceptions import ValidationError

from web3 import Web3


def validate_checksumed_address(address):
    if not Web3.isChecksumAddress(address):
        raise ValidationError(
            "%(address)s is not a valid ethereum address",
            params={"address": address},
        )
