from django.core.exceptions import ValidationError
from ethereum.utils import check_checksum


def validate_checksumed_address(address):
    if not check_checksum(address):
        raise ValidationError(
            '%(address)s has an invalid checksum',
            params={'address': address},
        )
