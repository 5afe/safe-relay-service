import os
from logging import getLogger
from typing import Dict, Iterable, List, Tuple

import rlp
from django.conf import settings
from eth_account.internal.transactions import (encode_transaction,
                                               serializable_unsigned_transaction_from_dict)
from ethereum.exceptions import InvalidTransaction
from ethereum.transactions import Transaction, secpk1n
from ethereum.utils import (check_checksum, checksum_encode,
                            mk_contract_address, privtoaddr)
from hexbytes import HexBytes
from web3 import HTTPProvider, Web3

from safe_relay_service.gas_station.gas_station import GasStation
from safe_relay_service.safe.models import SafeContract, SafeCreation

from .contracts import get_paying_proxy_contract, get_safe_contract
from .serializers import SafeTransactionCreationResponseSerializer
from .utils import NULL_ADDRESS

logger = getLogger(__name__)


def send_eth_to(w3, to: str, gas_price: int, value: int, gas: int=22000) -> str:
    """
    Send ether using configured account
    :param w3: Web3 instance
    :param to: to
    :param gas_price: gas_price
    :param value: value(wei)
    :param gas: gas, defaults to 22000
    :return: tx_hash
    """

    assert check_checksum(to)

    assert value < w3.toWei(settings.SAFE_FUNDER_MAX_ETH, 'ether')

    private_key = settings.SAFE_FUNDER_PRIVATE_KEY

    if private_key:
        ethereum_account = checksum_encode(privtoaddr(private_key))
        tx = {
                'to': to,
                'value': value,
                'gas': gas,
                'gasPrice': gas_price,
                'nonce': w3.eth.getTransactionCount(ethereum_account),
            }

        signed_tx = w3.eth.account.signTransaction(tx, private_key=private_key)
        logger.debug('Sending %d wei from %s to %s', value, ethereum_account, to)
        return w3.eth.sendRawTransaction(signed_tx.rawTransaction)
    elif w3.eth.accounts:
        ethereum_account = w3.eth.accounts[0]
        tx = {
                'from': ethereum_account,
                'to': to,
                'value': value,
                'gas': gas,
                'gasPrice': gas_price,
                'nonce': w3.eth.getTransactionCount(ethereum_account),
            }
        logger.debug('Sending %d wei from %s to %s', value, ethereum_account, to)
        return w3.eth.sendTransaction(tx)
    else:
        raise ValueError("Ethereum account was not configured or unlocked in the node")


def find_valid_random_signature(s: int) -> Tuple[int, int]:
    """
    Find v and r valid values for a given s
    :param s: random value
    :return: v, r
    """
    for _ in range(10000):
        r = int(os.urandom(31).hex(), 16)
        v = (r % 2) + 27
        if r < secpk1n:
            tx = Transaction(0, 1, 21000, b'', 0, b'', v=v, r=r, s=s)
            try:
                tx.sender
                return v, r
            except (InvalidTransaction, ValueError):
                logger.debug('Cannot find signature with v=%d r=%d s=%d', v, r, s)

    raise ValueError('Valid signature not found with s=%d', s)


def check_tx_with_confirmations(w3, tx_hash: str, confirmations: int) -> bool:
    """
    Check tx hash and make sure it has the confirmations required
    :param w3: Web3 instance
    :param tx_hash: Hash of the tx
    :param confirmations: Minimum number of confirmations required
    :return: True if tx was mined with the number of confirmations required, False otherwise
    """
    block_number = w3.eth.blockNumber
    tx_receipt = w3.eth.getTransactionReceipt(tx_hash)
    tx_block_number = tx_receipt['blockNumber']
    return (block_number - tx_block_number) >= confirmations


def create_safe_tx(s: int, owners: Iterable[str], threshold: int) -> SafeTransactionCreationResponseSerializer:
    """
    Create models for safe tx
    :param s:
    :param owners:
    :param threshold:
    :return:
    """
    gas_station = GasStation(settings.ETHEREUM_NODE_URL, settings.GAS_STATION_NUMBER_BLOCKS)
    w3 = Web3(HTTPProvider(settings.ETHEREUM_NODE_URL))

    if settings.SAFE_GAS_PRICE:
        gas_price = settings.SAFE_GAS_PRICE
    else:
        gas_price = gas_station.get_gas_prices().fast

    funder = checksum_encode(privtoaddr(settings.SAFE_FUNDER_PRIVATE_KEY)) if settings.SAFE_FUNDER_PRIVATE_KEY else None

    safe_creation_tx_builder = SafeCreationTxBuilder(w3=w3,
                                                     owners=owners,
                                                     threshold=threshold,
                                                     signature_s=s,
                                                     master_copy=settings.SAFE_PERSONAL_CONTRACT_ADDRESS,
                                                     gas_price=gas_price,
                                                     funder=funder)

    safe_transaction_response_data = SafeTransactionCreationResponseSerializer(data={
        'signature': {
            'v': safe_creation_tx_builder.v,
            'r': safe_creation_tx_builder.r,
            's': safe_creation_tx_builder.s,
        },
        'safe': safe_creation_tx_builder.safe_address,
        'tx': {
            'from': safe_creation_tx_builder.deployer_address,
            'value': safe_creation_tx_builder.contract_creation_tx.value,
            'data': safe_creation_tx_builder.contract_creation_tx.data.hex(),
            'gas': safe_creation_tx_builder.gas,
            'gas_price': safe_creation_tx_builder.gas_price,
            'nonce': safe_creation_tx_builder.contract_creation_tx.nonce,
        },
        'payment': safe_creation_tx_builder.payment
    })
    assert safe_transaction_response_data.is_valid()

    safe_contract = SafeContract.objects.create(address=safe_creation_tx_builder.safe_address)
    SafeCreation.objects.create(
        owners=owners,
        threshold=threshold,
        safe=safe_contract,
        deployer=safe_creation_tx_builder.deployer_address,
        signed_tx=safe_creation_tx_builder.raw_tx,
        tx_hash=safe_creation_tx_builder.tx_hash.hex(),
        gas=safe_creation_tx_builder.gas,
        gas_price=gas_price,
        v=safe_creation_tx_builder.v,
        r=safe_creation_tx_builder.r,
        s=safe_creation_tx_builder.s
    )

    return safe_transaction_response_data


class SafeCreationTxBuilder:
    def __init__(self, w3: Web3, owners: List[str], threshold: int, signature_s: int, master_copy: str,
                 gas_price: int, funder: str, payment_token: str=None):
        self.owners = owners
        self.threshold = threshold
        self.s = signature_s
        self.master_copy = master_copy
        self.gas_price = gas_price
        self.funder = funder
        self.payment_token = payment_token

        self.gnosis_safe_contract = get_safe_contract(w3, master_copy)
        self.paying_proxy_contract = get_paying_proxy_contract(w3)

        safe_tx = self._get_safe_tx(owners, threshold)
        encoded_data = safe_tx['data']

        self.gas = self._calculate_gas(owners, encoded_data)

        self.payment = self.gas * gas_price

        self.contract_creation_tx_dict = self._build_proxy_contract_creation_tx(master_copy=master_copy,
                                                                                initializer=encoded_data,
                                                                                funder=funder,
                                                                                payment_token=payment_token,
                                                                                payment=self.payment,
                                                                                gas=self.gas,
                                                                                gas_price=gas_price)

        (self.contract_creation_tx,
         self.v,
         self.r) = self._generate_valid_transaction(gas_price,
                                                    self.gas,
                                                    self.contract_creation_tx_dict['data'],
                                                    self.s
                                                    )
        self.raw_tx = rlp.encode(self.contract_creation_tx)
        self.tx_hash = self.contract_creation_tx.hash
        self.deployer_address = checksum_encode(self.contract_creation_tx.sender)
        self.safe_address = checksum_encode(mk_contract_address(self.deployer_address, nonce=0))

    @staticmethod
    def _calculate_gas(owners: List[str], encoded_data: bytes) -> int:
        base_gas = 21000  # Transaction standard gas
        data_gas = 68 * len(encoded_data)  # Data gas
        gas_per_owner = 18020  # Magic number calculated by testing and averaging owners
        return base_gas + data_gas + 270000 + len(owners) * gas_per_owner

    def _get_safe_tx(self, owners: List[str], threshold: int) -> bytes:
        return self.gnosis_safe_contract.functions.setup(
            owners,
            threshold,
            NULL_ADDRESS,
            b''
        ).buildTransaction({
            'gas': 1,
            'gasPrice': 1,
        })

    def _build_proxy_contract_creation_tx(self,
                                          master_copy: str,
                                          initializer: bytes,
                                          funder: str,
                                          payment_token: str,
                                          payment: int,
                                          gas: int,
                                          gas_price: int,
                                          nonce: int=0):
        """
        :param master_copy: Master Copy of Gnosis Safe already deployed
        :param initializer: Data initializer to send to GnosisSafe setup method
        :param funder: Address that should get the payment (if payment set)
        :param payment_token: Address if a token is used. If not set, 0x0 will be ether
        :param payment: Payment
        :return: Transaction dictionary
        """
        if not funder or funder == NULL_ADDRESS:
            funder = NULL_ADDRESS
            payment = 0

        payment_token = payment_token if payment_token else NULL_ADDRESS

        return self.paying_proxy_contract.constructor(
            master_copy,
            initializer,
            funder,
            payment_token,
            payment
        ).buildTransaction({
            'gas': gas,
            'gasPrice': gas_price,
            'nonce': nonce,
        })

    @staticmethod
    def _generate_valid_transaction(gas_price: int, gas: int, data: str, s: int, nonce: int=0) -> Tuple[Transaction,
                                                                                                        int, int]:
        for _ in range(100):
            try:
                v, r = find_valid_random_signature(s)
                contract_creation_tx = Transaction(nonce, gas_price, gas, b'', 0, HexBytes(data), v=v, r=r, s=s)
                contract_creation_tx.sender
                return contract_creation_tx, v, r
            except InvalidTransaction:
                pass
        raise ValueError('Valid signature not found with s=%d', s)

    @staticmethod
    def _sign_web3_transaction(tx: Dict[str, any], v: int, r: int, s: int) -> (bytes, HexBytes):
        """
        Signed transaction can be send with w3.eth.sendRawTransaction
        """
        unsigned_transaction = serializable_unsigned_transaction_from_dict(tx)
        rlp_encoded_transaction = encode_transaction(unsigned_transaction, vrs=(v, r, s))

        # To get the address signing, just do ecrecover_to_pub(unsigned_transaction.hash(), v, r, s)
        return rlp_encoded_transaction, unsigned_transaction.hash()
