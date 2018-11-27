import os
from logging import getLogger

import factory
import factory.fuzzy
from django_eth.constants import (SIGNATURE_R_MAX_VALUE, SIGNATURE_R_MIN_VALUE,
                                  SIGNATURE_S_MAX_VALUE, SIGNATURE_S_MIN_VALUE,
                                  SIGNATURE_V_MAX_VALUE, SIGNATURE_V_MIN_VALUE)
from django_eth.tests.factories import get_eth_address_with_key
from ethereum.transactions import secpk1n
from gnosis.safe.tests.factories import generate_valid_s
from hexbytes import HexBytes
from web3 import Web3

from ..models import SafeContract, SafeCreation, SafeFunding

logger = getLogger(__name__)


class SafeContractFactory(factory.DjangoModelFactory):
    class Meta:
        model = SafeContract

    address = factory.LazyFunction(lambda: get_eth_address_with_key()[0])
    master_copy = factory.LazyFunction(lambda: get_eth_address_with_key()[0])


class SafeCreationFactory(factory.DjangoModelFactory):
    class Meta:
        model = SafeCreation

    deployer = factory.LazyFunction(lambda: get_eth_address_with_key()[0])
    safe = factory.SubFactory(SafeContractFactory)
    funder = factory.LazyFunction(lambda: get_eth_address_with_key()[0])
    owners = factory.LazyFunction(lambda: [get_eth_address_with_key()[0], get_eth_address_with_key()[0]])
    threshold = 2
    payment = factory.fuzzy.FuzzyInteger(100, 1000)
    payment_ether = factory.fuzzy.FuzzyInteger(100, 1000)
    tx_hash = factory.Sequence(lambda n: Web3.sha3(n))
    gas = factory.fuzzy.FuzzyInteger(100000, 200000)
    gas_price = factory.fuzzy.FuzzyInteger(Web3.toWei(1, 'gwei'), Web3.toWei(20, 'gwei'))
    payment_token = None
    value = 0
    v = factory.fuzzy.FuzzyInteger(SIGNATURE_V_MIN_VALUE, SIGNATURE_V_MAX_VALUE)
    r = factory.fuzzy.FuzzyInteger(SIGNATURE_R_MIN_VALUE, SIGNATURE_R_MAX_VALUE)
    s = factory.fuzzy.FuzzyInteger(SIGNATURE_S_MIN_VALUE, SIGNATURE_S_MAX_VALUE)
    data = factory.Sequence(lambda n: HexBytes('%x' % (n + 1000)))
    signed_tx = factory.Sequence(lambda n: HexBytes('%x' % (n + 5000)))


class SafeFundingFactory(factory.DjangoModelFactory):
    class Meta:
        model = SafeFunding

    safe = factory.SubFactory(SafeContractFactory)


def generate_valid_s():
    while True:
        s = int(os.urandom(30).hex(), 16)
        if s <= (secpk1n // 2):
            return s


def generate_safe(owners=None, number_owners=3, threshold=None, payment_token=None) -> SafeCreation:
    s = generate_valid_s()

    if not owners:
        owners = []
        for _ in range(number_owners):
            owner, _ = get_eth_address_with_key()
            owners.append(owner)

    threshold = threshold if threshold else len(owners)

    safe_creation = SafeCreation.objects.create_safe_tx(s, owners, threshold, payment_token)
    return safe_creation


#FIXME Use the functions in gnosis-py
def deploy_safe(w3, safe_creation, funder: str, initial_funding_wei: int=0) -> str:
    w3.eth.waitForTransactionReceipt(
        w3.eth.sendTransaction({
            'from': funder,
            'to': safe_creation.deployer,
            'value': safe_creation.payment
        })
    )

    w3.eth.waitForTransactionReceipt(
        w3.eth.sendTransaction({
            'from': funder,
            'to': safe_creation.safe.address,
            'value': safe_creation.payment
        })
    )

    tx_hash = w3.eth.sendRawTransaction(bytes(safe_creation.signed_tx))
    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
    assert tx_receipt.contractAddress == safe_creation.safe.address
    assert tx_receipt.status

    if initial_funding_wei > 0:
        w3.eth.waitForTransactionReceipt(
            w3.eth.sendTransaction({
                'from': funder,
                'to': safe_creation.safe.address,
                'value': initial_funding_wei
            })
        )

    return safe_creation.safe.address
