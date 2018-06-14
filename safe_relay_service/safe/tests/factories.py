import os
from logging import getLogger
from typing import Tuple

from ethereum.transactions import secpk1n
from faker import Factory as FakerFactory
from faker import Faker

from safe_relay_service.ether.tests.factories import get_eth_address_with_key

from ..helpers import create_safe_tx

fakerFactory = FakerFactory.create()
faker = Faker()

logger = getLogger(__name__)


def generate_valid_s():
    while True:
        s = int(os.urandom(31).hex(), 16)
        if s <= (secpk1n - 1):
            return s


def generate_safe() -> Tuple[str, str, int]:
    s = generate_valid_s()
    owner1, _ = get_eth_address_with_key()
    owner2, _ = get_eth_address_with_key()
    owner3, _ = get_eth_address_with_key()
    owner4, _ = get_eth_address_with_key()
    owners = [owner1, owner2, owner3, owner4]
    threshold = len(owners) - 1

    s = create_safe_tx(s, owners, threshold)
    safe, deployer, payment = s.data['safe'], s.data['tx']['from'], int(s.data['payment'])
    return safe, deployer, payment
