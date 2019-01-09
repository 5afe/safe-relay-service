from logging import getLogger

import factory.fuzzy
from ethereum.utils import checksum_encode, mk_contract_address
from hexbytes import HexBytes
from web3 import Web3

from gnosis.eth.constants import (SIGNATURE_R_MAX_VALUE, SIGNATURE_R_MIN_VALUE,
                                  SIGNATURE_S_MAX_VALUE, SIGNATURE_S_MIN_VALUE,
                                  SIGNATURE_V_MAX_VALUE, SIGNATURE_V_MIN_VALUE)
from gnosis.eth.utils import get_eth_address_with_key

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
    safe = factory.SubFactory(SafeContractFactory,
                              address=factory.LazyAttribute(lambda o:
                                                            checksum_encode(mk_contract_address(
                                                                o.factory_parent.deployer, 0))))
    funder = factory.LazyFunction(lambda: get_eth_address_with_key()[0])
    owners = factory.LazyFunction(lambda: [get_eth_address_with_key()[0], get_eth_address_with_key()[0]])
    threshold = 2
    payment = factory.fuzzy.FuzzyInteger(100, 1000)
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
