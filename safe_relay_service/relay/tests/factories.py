from logging import getLogger

import factory.fuzzy
from eth_account import Account
from ethereum.utils import checksum_encode, mk_contract_address
from hexbytes import HexBytes
from web3 import Web3

from gnosis.eth.constants import (NULL_ADDRESS, SIGNATURE_R_MAX_VALUE,
                                  SIGNATURE_R_MIN_VALUE, SIGNATURE_S_MAX_VALUE,
                                  SIGNATURE_S_MIN_VALUE, SIGNATURE_V_MAX_VALUE,
                                  SIGNATURE_V_MIN_VALUE)
from gnosis.eth.utils import get_eth_address_with_key

from ..models import (EthereumTx, EthereumTxCallType, InternalTx, SafeContract,
                      SafeCreation, SafeCreation2, SafeFunding, SafeMultisigTx,
                      SafeTxStatus)

logger = getLogger(__name__)


class SafeContractFactory(factory.DjangoModelFactory):
    class Meta:
        model = SafeContract

    address = factory.LazyFunction(lambda: Account.create().address)
    master_copy = factory.LazyFunction(lambda: Account.create().address)


class SafeCreationFactory(factory.DjangoModelFactory):
    class Meta:
        model = SafeCreation

    deployer = factory.LazyFunction(lambda: Account.create().address)
    safe = factory.SubFactory(SafeContractFactory,
                              address=factory.LazyAttribute(lambda o:
                                                            checksum_encode(mk_contract_address(
                                                                o.factory_parent.deployer, 0))))
    funder = factory.LazyFunction(lambda: Account.create().address)
    owners = factory.LazyFunction(lambda: [Account.create().address, Account.create().address])
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


class SafeCreation2Factory(factory.DjangoModelFactory):
    class Meta:
        model = SafeCreation2

    safe = factory.SubFactory(SafeContractFactory,
                              address=factory.LazyAttribute(lambda o:
                                                            checksum_encode(mk_contract_address(
                                                                o.factory_parent.proxy_factory, 0))))
    master_copy = factory.LazyFunction(lambda: Account.create().address)
    proxy_factory = factory.LazyFunction(lambda: Account.create().address)
    salt_nonce = factory.fuzzy.FuzzyInteger(1, 10000000)
    owners = factory.LazyFunction(lambda: [Account.create().address, Account.create().address])
    threshold = 2
    payment_token = None
    payment = factory.fuzzy.FuzzyInteger(100, 100000)
    payment_receiver = NULL_ADDRESS
    setup_data = factory.Sequence(lambda n: HexBytes('%x' % (n + 1000)))
    gas_estimated = factory.fuzzy.FuzzyInteger(100000, 200000)
    gas_price_estimated = factory.fuzzy.FuzzyInteger(Web3.toWei(1, 'gwei'), Web3.toWei(20, 'gwei'))
    tx_hash = factory.Sequence(lambda n: Web3.sha3(text='safe-creation-2-%d' % n))
    block_number = None


class SafeFundingFactory(factory.DjangoModelFactory):
    class Meta:
        model = SafeFunding

    safe = factory.SubFactory(SafeContractFactory)


class EthereumTxFactory(factory.DjangoModelFactory):
    class Meta:
        model = EthereumTx

    tx_hash = factory.Sequence(lambda n: Web3.sha3(text='ethereum_tx_hash%d' % n))
    block_number = 0
    _from = factory.LazyFunction(lambda: Account.create().address)
    gas = factory.fuzzy.FuzzyInteger(1000, 5000)
    gas_price = factory.fuzzy.FuzzyInteger(1, 100)
    data = factory.Sequence(lambda n: HexBytes('%x' % (n + 1000)))
    nonce = factory.Sequence(lambda n: n)
    to = factory.LazyFunction(lambda: Account.create().address)
    value = factory.fuzzy.FuzzyInteger(0, 1000)


class SafeMultisigTxFactory(factory.DjangoModelFactory):
    class Meta:
        model = SafeMultisigTx

    safe = factory.SubFactory(SafeContractFactory)
    ethereum_tx = factory.SubFactory(EthereumTxFactory)
    to = factory.LazyFunction(lambda: Account.create().address)
    value = factory.fuzzy.FuzzyInteger(0, 1000)
    data = factory.Sequence(lambda n: HexBytes('%x' % (n + 1000)))
    operation = 0
    safe_tx_gas = factory.fuzzy.FuzzyInteger(1000, 5000)
    data_gas = factory.fuzzy.FuzzyInteger(100, 500)
    gas_price = factory.fuzzy.FuzzyInteger(1, 100)
    gas_token = None
    refund_receiver = factory.LazyFunction(lambda: Account.create().address)
    nonce = factory.Sequence(lambda n: n)
    safe_tx_hash = factory.Sequence(lambda n: Web3.sha3(text='safe_tx_hash%d' % n))


class InternalTxFactory(factory.DjangoModelFactory):
    class Meta:
        model = InternalTx

    ethereum_tx = factory.SubFactory(EthereumTxFactory)
    _from = factory.LazyFunction(lambda: Account.create().address)
    gas = factory.fuzzy.FuzzyInteger(1000, 5000)
    data = factory.Sequence(lambda n: HexBytes('%x' % (n + 1000)))
    to = factory.LazyFunction(lambda: Account.create().address)
    value = factory.fuzzy.FuzzyInteger(0, 1000)
    gas_used = factory.fuzzy.FuzzyInteger(1000, 5000)
    contract_address = None
    code = None
    output = None
    call_type = EthereumTxCallType.CALL.value
    trace_address = factory.Sequence(lambda n: n)


class SafeTxStatusFactory(factory.DjangoModelFactory):
    class Meta:
        model = SafeTxStatus

    safe = factory.SubFactory(SafeContractFactory)
