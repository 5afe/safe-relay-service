from logging import getLogger
from typing import Iterable

from django.conf import settings
from django.core.cache import cache
from ethereum.utils import check_checksum, checksum_encode, privtoaddr
from web3 import HTTPProvider, Web3

from safe_relay_service.gas_station.gas_station import GasStation

from .helpers import SafeCreationTxBuilder

logger = getLogger(__name__)


# TODO: Use INCR and DECR on redis instead of cache

class EthereumService:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = super().__new__(cls)
        return cls.instance

    def __init__(self):
        self.w3 = Web3(HTTPProvider(settings.ETHEREUM_NODE_URL))
        self.gas_station = GasStation(settings.ETHEREUM_NODE_URL, settings.GAS_STATION_NUMBER_BLOCKS)

    def _get_nonce_cache_key(self, address):
        return 'nonce:%s' % address

    def get_nonce_for_account(self, address):
        cache_key = self._get_nonce_cache_key(address)
        nonce = cache.get(cache_key)
        if nonce:
            nonce += 1
        else:
            nonce = 0
        nonce = max(nonce, self.w3.eth.getTransactionCount(address))
        cache.set(cache_key, nonce)
        return nonce

    def _decrease_nonce_for_account(self, address):
        cache_key = self._get_nonce_cache_key(address)
        nonce = cache.get(cache_key)
        if nonce:
            nonce -= 1
            cache.set(cache_key, nonce)
            return nonce

    @property
    def current_block_number(self):
        return self.w3.eth.blockNumber

    def get_balance(self, address, block_identifier=None):
        return self.w3.eth.getBalance(address, block_identifier)

    def get_transaction_receipt(self, tx_hash):
        return self.w3.eth.getTransactionReceipt(tx_hash)

    def send_raw_transaction(self, raw_transaction):
        return self.w3.eth.sendRawTransaction(bytes(raw_transaction))

    def send_eth_to(self, to: str, gas_price: int, value: int, gas: int=22000) -> bytes:
        """
        Send ether using configured account
        :param to: to
        :param gas_price: gas_price
        :param value: value(wei)
        :param gas: gas, defaults to 22000
        :return: tx_hash
        """

        assert check_checksum(to)

        assert value < self.w3.toWei(settings.SAFE_FUNDER_MAX_ETH, 'ether')

        private_key = settings.SAFE_FUNDER_PRIVATE_KEY

        try:
            if private_key:
                ethereum_account = self.private_key_to_checksumed_address(private_key)
                tx = {
                        'to': to,
                        'value': value,
                        'gas': gas,
                        'gasPrice': gas_price,
                        'nonce': self.get_nonce_for_account(ethereum_account),
                    }

                signed_tx = self.w3.eth.account.signTransaction(tx, private_key=private_key)
                logger.debug('Sending %d wei from %s to %s', value, ethereum_account, to)
                return self.w3.eth.sendRawTransaction(signed_tx.rawTransaction)
            elif self.w3.eth.accounts:
                ethereum_account = self.w3.eth.accounts[0]
                tx = {
                        'from': ethereum_account,
                        'to': to,
                        'value': value,
                        'gas': gas,
                        'gasPrice': gas_price,
                        'nonce': self.get_nonce_for_account(ethereum_account),
                    }
                logger.debug('Sending %d wei from %s to %s', value, ethereum_account, to)
                return self.w3.eth.sendTransaction(tx)
            else:
                ethereum_account = None
                logger.error('No ethereum account configured')
                raise ValueError("Ethereum account was not configured or unlocked in the node")
        except Exception as e:
            self._decrease_nonce_for_account(ethereum_account)
            raise e

    def check_tx_with_confirmations(self, tx_hash: str, confirmations: int) -> bool:
        """
        Check tx hash and make sure it has the confirmations required
        :param w3: Web3 instance
        :param tx_hash: Hash of the tx
        :param confirmations: Minimum number of confirmations required
        :return: True if tx was mined with the number of confirmations required, False otherwise
        """
        tx_receipt = self.w3.eth.getTransactionReceipt(tx_hash)
        if not tx_receipt:
            return False
        else:
            block_number = self.w3.eth.blockNumber
            tx_block_number = tx_receipt['blockNumber']
            return (block_number - tx_block_number) >= confirmations

    @staticmethod
    def private_key_to_checksumed_address(private_key):
        return checksum_encode(privtoaddr(private_key))

    def get_safe_creation_tx_builder(self, s: int, owners: Iterable[str], threshold: int) -> SafeCreationTxBuilder:
        master_copy = settings.SAFE_PERSONAL_CONTRACT_ADDRESS
        gas_price = settings.SAFE_GAS_PRICE

        if not gas_price:
            gas_price = self.gas_station.get_gas_prices().fast

        funder = self.private_key_to_checksumed_address(settings.SAFE_FUNDER_PRIVATE_KEY)\
            if settings.SAFE_FUNDER_PRIVATE_KEY else None

        safe_creation_tx_builder = SafeCreationTxBuilder(w3=self.w3,
                                                         owners=owners,
                                                         threshold=threshold,
                                                         signature_s=s,
                                                         master_copy=master_copy,
                                                         gas_price=gas_price,
                                                         funder=funder)

        assert safe_creation_tx_builder.contract_creation_tx.nonce == 0
        return safe_creation_tx_builder
