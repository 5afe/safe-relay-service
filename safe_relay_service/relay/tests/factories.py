from logging import getLogger

from django.utils import timezone

import factory.fuzzy
from eth_account import Account
from factory.django import DjangoModelFactory
from hexbytes import HexBytes
from web3 import Web3

from gnosis.eth.constants import (
    ERC20_721_TRANSFER_TOPIC,
    NULL_ADDRESS,
    SIGNATURE_R_MAX_VALUE,
    SIGNATURE_R_MIN_VALUE,
    SIGNATURE_S_MAX_VALUE,
    SIGNATURE_S_MIN_VALUE,
    SIGNATURE_V_MAX_VALUE,
    SIGNATURE_V_MIN_VALUE,
)
from gnosis.eth.utils import mk_contract_address

from ..models import (
    BannedSigner,
    EthereumBlock,
    EthereumEvent,
    EthereumTx,
    SafeContract,
    SafeCreation,
    SafeCreation2,
    SafeFunding,
    SafeMultisigTx,
    SafeTxStatus,
)

logger = getLogger(__name__)


class SafeContractFactory(DjangoModelFactory):
    class Meta:
        model = SafeContract

    address = factory.LazyFunction(lambda: Account.create().address)
    master_copy = factory.LazyFunction(lambda: Account.create().address)


class SafeCreationFactory(DjangoModelFactory):
    class Meta:
        model = SafeCreation

    deployer = factory.LazyFunction(lambda: Account.create().address)
    safe = factory.SubFactory(
        SafeContractFactory,
        address=factory.LazyAttribute(
            lambda o: mk_contract_address(o.factory_parent.deployer, 0)
        ),
    )
    funder = factory.LazyFunction(lambda: Account.create().address)
    owners = factory.LazyFunction(
        lambda: [Account.create().address, Account.create().address]
    )
    threshold = 2
    payment = factory.fuzzy.FuzzyInteger(100, 1000)
    tx_hash = factory.Sequence(lambda n: Web3.keccak(n))
    gas = factory.fuzzy.FuzzyInteger(100000, 200000)
    gas_price = factory.fuzzy.FuzzyInteger(
        Web3.toWei(1, "gwei"), Web3.toWei(20, "gwei")
    )
    payment_token = None
    value = 0
    v = factory.fuzzy.FuzzyInteger(SIGNATURE_V_MIN_VALUE, SIGNATURE_V_MAX_VALUE)
    r = factory.fuzzy.FuzzyInteger(SIGNATURE_R_MIN_VALUE, SIGNATURE_R_MAX_VALUE)
    s = factory.fuzzy.FuzzyInteger(SIGNATURE_S_MIN_VALUE, SIGNATURE_S_MAX_VALUE)
    data = factory.Sequence(lambda n: HexBytes("%x" % (n + 1000)))
    signed_tx = factory.Sequence(lambda n: HexBytes("%x" % (n + 5000)))


class SafeCreation2Factory(DjangoModelFactory):
    class Meta:
        model = SafeCreation2

    safe = factory.SubFactory(
        SafeContractFactory,
        address=factory.LazyAttribute(
            lambda o: mk_contract_address(o.factory_parent.proxy_factory, 0)
        ),
    )
    master_copy = factory.LazyFunction(lambda: Account.create().address)
    proxy_factory = factory.LazyFunction(lambda: Account.create().address)
    salt_nonce = factory.fuzzy.FuzzyInteger(1, 10000000)
    owners = factory.LazyFunction(
        lambda: [Account.create().address, Account.create().address]
    )
    threshold = 2
    payment_token = None
    payment = factory.fuzzy.FuzzyInteger(100, 100000)
    payment_receiver = NULL_ADDRESS
    setup_data = factory.Sequence(lambda n: HexBytes("%x" % (n + 1000)))
    gas_estimated = factory.fuzzy.FuzzyInteger(100000, 200000)
    gas_price_estimated = factory.fuzzy.FuzzyInteger(
        Web3.toWei(1, "gwei"), Web3.toWei(20, "gwei")
    )
    tx_hash = factory.Sequence(lambda n: Web3.keccak(text="safe-creation-2-%d" % n))
    block_number = None


class SafeFundingFactory(DjangoModelFactory):
    class Meta:
        model = SafeFunding

    safe = factory.SubFactory(SafeContractFactory)


class EthereumBlockFactory(DjangoModelFactory):
    class Meta:
        model = EthereumBlock

    number = factory.Sequence(lambda n: n)
    gas_limit = factory.fuzzy.FuzzyInteger(100000000, 200000000)
    gas_used = factory.fuzzy.FuzzyInteger(100000, 500000)
    timestamp = factory.LazyFunction(timezone.now)
    block_hash = factory.Sequence(lambda n: Web3.keccak(text="block%d" % n))


class EthereumTxFactory(DjangoModelFactory):
    class Meta:
        model = EthereumTx

    block = factory.SubFactory(EthereumBlockFactory)
    tx_hash = factory.Sequence(lambda n: Web3.keccak(text="ethereum_tx_hash%d" % n))
    gas_used = factory.fuzzy.FuzzyInteger(100000, 500000)
    status = 1  # Success
    transaction_index = factory.Sequence(lambda n: n)
    _from = factory.LazyFunction(lambda: Account.create().address)
    gas = factory.fuzzy.FuzzyInteger(1000, 5000)
    gas_price = factory.fuzzy.FuzzyInteger(1, 100)
    data = factory.Sequence(lambda n: HexBytes("%x" % (n + 1000)))
    nonce = factory.Sequence(lambda n: n)
    to = factory.LazyFunction(lambda: Account.create().address)
    value = factory.fuzzy.FuzzyInteger(0, 1000)


class SafeMultisigTxFactory(DjangoModelFactory):
    class Meta:
        model = SafeMultisigTx

    safe = factory.SubFactory(SafeContractFactory)
    ethereum_tx = factory.SubFactory(EthereumTxFactory)
    to = factory.LazyFunction(lambda: Account.create().address)
    value = factory.fuzzy.FuzzyInteger(0, 1000)
    data = factory.Sequence(lambda n: HexBytes("%x" % (n + 1000)))
    operation = 0
    safe_tx_gas = factory.fuzzy.FuzzyInteger(1000, 5000)
    data_gas = factory.fuzzy.FuzzyInteger(100, 500)
    gas_price = factory.fuzzy.FuzzyInteger(1, 100)
    gas_token = None
    refund_receiver = factory.LazyFunction(lambda: Account.create().address)
    nonce = factory.Sequence(lambda n: n)
    safe_tx_hash = factory.Sequence(lambda n: Web3.keccak(text="safe_tx_hash%d" % n))


class SafeTxStatusFactory(DjangoModelFactory):
    class Meta:
        model = SafeTxStatus

    safe = factory.SubFactory(SafeContractFactory)


class EthereumEventFactory(DjangoModelFactory):
    class Meta:
        model = EthereumEvent

    class Params:
        to = None
        from_ = None
        erc721 = False
        value = 1200

    ethereum_tx = factory.SubFactory(EthereumTxFactory)
    log_index = factory.Sequence(lambda n: n)
    token_address = factory.LazyFunction(lambda: Account.create().address)
    topic = ERC20_721_TRANSFER_TOPIC
    arguments = factory.LazyAttribute(
        lambda o: {
            "to": o.to if o.to else Account.create().address,
            "from": o.from_ if o.from_ else Account.create().address,
            "tokenId" if o.erc721 else "value": o.value,
        }
    )


class BannedSignerFactory(DjangoModelFactory):
    class Meta:
        model = BannedSigner

    address = factory.LazyFunction(lambda: Account.create().address)
