import os
from logging import getLogger

from ethereum.transactions import secpk1n
from faker import Factory as FakerFactory
from faker import Faker

fakerFactory = FakerFactory.create()
faker = Faker()

logger = getLogger(__name__)


def generate_valid_s():
    while True:
        s = int(os.urandom(31).hex(), 16)
        if s <= (secpk1n - 1):
            return s
