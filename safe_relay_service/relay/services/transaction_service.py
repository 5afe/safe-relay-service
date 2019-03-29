from logging import getLogger
from typing import Dict, List, NamedTuple, Optional, Tuple

from eth_account import Account
from redis import Redis

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.safe.exceptions import SafeServiceException
from gnosis.safe.safe_service import SafeService, SafeServiceProvider
from gnosis.safe.signatures import signatures_to_bytes

from safe_relay_service.gas_station.gas_station import (GasStation,
                                                        GasStationProvider)
from safe_relay_service.tokens.models import Token

from ..models import SafeContract, SafeMultisigTx
from ..repositories.redis_repository import RedisRepository

logger = getLogger(__name__)


class TransactionServiceException(Exception):
    pass


class RefundMustBeEnabled(TransactionServiceException):
    pass


class InvalidGasToken(TransactionServiceException):
    pass


class SignaturesNotFound(TransactionServiceException):
    pass


class SignaturesNotSorted(TransactionServiceException):
    pass


class SafeMultisigTxExists(TransactionServiceException):
    pass


class NotEnoughFundsForMultisigTx(TransactionServiceException):
    pass


class InvalidMasterCopyAddress(TransactionServiceException):
    pass


class InvalidProxyContract(TransactionServiceException):
    pass


class InvalidRefundReceiver(TransactionServiceException):
    pass


class InvalidGasEstimation(TransactionServiceException):
    pass


class GasPriceTooLow(TransactionServiceException):
    pass


class TransactionEstimation(NamedTuple):
    safe_tx_gas: int
    data_gas: int
    operational_gas: int
    gas_price: int
    gas_token: str
    last_used_nonce: int


class TransactionServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            cls.instance = TransactionService(SafeServiceProvider(), GasStationProvider(),
                                              EthereumClientProvider(),
                                              RedisRepository().redis,
                                              settings.SAFE_VALID_CONTRACT_ADDRESSES,
                                              settings.SAFE_TX_SENDER_PRIVATE_KEY)
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class TransactionService:
    def __init__(self, safe_service: SafeService, gas_station: GasStation, ethereum_client: EthereumClient,
                 redis: Redis, safe_valid_contract_addresses: str, tx_sender_private_key: str):
        self.safe_service = safe_service
        self.gas_station = gas_station
        self.ethereum_client = ethereum_client
        self.redis = redis
        self.safe_valid_contract_addresses = safe_valid_contract_addresses
        self.tx_sender_account = Account.privateKeyToAccount(tx_sender_private_key)

    @staticmethod
    def _check_refund_receiver(refund_receiver: str) -> bool:
        """
        We only support tx.origin as refund receiver right now
        In the future we can also accept transactions where it is set to our service account to receive the payments.
        This would prevent that anybody can front-run our service
        """
        return refund_receiver == NULL_ADDRESS

    @staticmethod
    def _is_valid_gas_token(address: str) -> float:
        """
        :param address: Token address
        :return: bool if gas token, false otherwise
        """
        address = address or NULL_ADDRESS
        if address == NULL_ADDRESS:
            return True
        try:
            Token.objects.get(address=address, gas=True)
            return True
        except Token.DoesNotExist:
            logger.warning('Cannot retrieve gas token from db: Gas token %s not valid' % address)
            return False

    def _check_safe_gas_price(self, gas_token: Optional[str], safe_gas_price: int) -> bool:
        """
        Check that `safe_gas_price` is not too low, so that the relay gets a full refund
        for the tx. Gas_price must be always > 0, if not refunding would be disabled
        If a `gas_token` is used we need to calculate the `gas_price` in Eth
        Gas price must be at least >= _current standard gas price_ > 0
        :param gas_token: Address of token is used, `NULL_ADDRESS` or `None` if it's ETH
        :return:
        :exception GasPriceTooLow
        :exception InvalidGasToken
        """
        if safe_gas_price < 1:
            raise RefundMustBeEnabled('Tx internal gas price cannot be 0 or less, it was %d' % safe_gas_price)

        current_standard_gas_price = self.gas_station.get_gas_prices().standard
        if gas_token and gas_token != NULL_ADDRESS:
            try:
                gas_token_model = Token.objects.get(address=gas_token, gas=True)
                estimated_gas_price = gas_token_model.calculate_gas_price(current_standard_gas_price)
                if safe_gas_price < estimated_gas_price:
                    raise GasPriceTooLow('Required gas-price>=%d to use gas-token' % estimated_gas_price)
                # We use gas station tx gas price. We cannot use internal tx's because is calculated
                # based on the gas token
            except Token.DoesNotExist:
                logger.warning('Cannot retrieve gas token from db: Gas token %s not valid' % gas_token)
                raise InvalidGasToken('Gas token %s not valid' % gas_token)
        else:
            if safe_gas_price < current_standard_gas_price:
                raise GasPriceTooLow('Required gas-price>=%d' % current_standard_gas_price)
        return True

    def _estimate_tx_gas_price(self, gas_token: Optional[str] = None):
        gas_price_fast = self.gas_station.get_gas_prices().fast
        if gas_token and gas_token != NULL_ADDRESS:
            try:
                gas_token_model = Token.objects.get(address=gas_token, gas=True)
                return gas_token_model.calculate_gas_price(gas_price_fast)
            except Token.DoesNotExist:
                raise InvalidGasToken('Gas token %s not found' % gas_token)
        else:
            return gas_price_fast

    def estimate_tx(self, safe_address: str, to: str, value: int, data: str, operation: int,
                    gas_token: Optional[str]) -> TransactionEstimation:
        """
        :return: TransactionEstimation with costs and last used nonce of safe
        :raises: InvalidGasToken: If Gas Token is not valid
        """
        if not self._is_valid_gas_token(gas_token):
            raise InvalidGasToken(gas_token)
        last_used_nonce = SafeMultisigTx.objects.get_last_nonce_for_safe(safe_address)
        safe_tx_gas = self.safe_service.estimate_tx_gas(safe_address, to, value, data, operation)
        safe_data_tx_gas = self.safe_service.estimate_tx_data_gas(safe_address, to, value, data, operation, gas_token,
                                                                  safe_tx_gas)
        safe_operational_tx_gas = self.safe_service.estimate_tx_operational_gas(safe_address,
                                                                                len(data) if data else 0)
        # Can throw RelayServiceException
        gas_price = self._estimate_tx_gas_price(gas_token)
        return TransactionEstimation(safe_tx_gas, safe_data_tx_gas, safe_operational_tx_gas, gas_price,
                                     gas_token or NULL_ADDRESS, last_used_nonce)

    def create_multisig_tx(self,
                           safe_address: str,
                           to: str,
                           value: int,
                           data: bytes,
                           operation: int,
                           safe_tx_gas: int,
                           data_gas: int,
                           gas_price: int,
                           gas_token: str,
                           refund_receiver: str,
                           nonce: int,
                           signatures: List[Dict[str, int]]) -> SafeMultisigTx:
        """
        :return: Database model of SafeMultisigTx
        :raises: SafeMultisigTxExists: If Safe Multisig Tx with nonce already exists
        :raises: InvalidGasToken: If Gas Token is not valid
        :raises: TransactionServiceException: If Safe Tx is not valid (not sorted owners, bad signature, bad nonce...)
        """

        safe_contract = SafeContract.objects.get(address=safe_address)

        if SafeMultisigTx.objects.filter(safe=safe_address, nonce=nonce).exists():
            raise SafeMultisigTxExists('Tx with nonce=%d for safe=%s already exists in DB' % (nonce, safe_address))

        signature_pairs = [(s['v'], s['r'], s['s']) for s in signatures]
        signatures_packed = signatures_to_bytes(signature_pairs)

        try:
            tx_hash, safe_tx_hash, tx = self._send_multisig_tx(
                safe_address,
                to,
                value,
                data,
                operation,
                safe_tx_gas,
                data_gas,
                gas_price,
                gas_token,
                refund_receiver,
                nonce,
                signatures_packed
            )
        except SafeServiceException as exc:
            raise TransactionServiceException(str(exc)) from exc

        return SafeMultisigTx.objects.create(
            safe=safe_contract,
            to=to,
            value=value,
            data=data,
            operation=operation,
            safe_tx_gas=safe_tx_gas,
            data_gas=data_gas,
            gas_price=gas_price,
            gas_token=None if gas_token == NULL_ADDRESS else gas_token,
            refund_receiver=refund_receiver,
            nonce=nonce,
            signatures=signatures_packed,
            gas=tx['gas'],
            safe_tx_hash=safe_tx_hash,
            tx_hash=tx_hash,
            tx_mined=False
        )

    def _send_multisig_tx(self,
                          safe_address: str,
                          to: str,
                          value: int,
                          data: bytes,
                          operation: int,
                          safe_tx_gas: int,
                          data_gas: int,
                          gas_price: int,
                          gas_token: str,
                          refund_receiver: str,
                          safe_nonce: int,
                          signatures: bytes,
                          tx_gas=None,
                          block_identifier='pending') -> Tuple[bytes, bytes, Dict[str, any]]:
        """
        This function calls the `send_multisig_tx` of the SafeService, but has some limitations to prevent abusing
        the relay
        :return: Tuple(tx_hash, safe_tx_hash, tx)
        :raises: InvalidMultisigTx: If user tx cannot go through the Safe
        """

        data = data or b''
        gas_token = gas_token or NULL_ADDRESS
        refund_receiver = refund_receiver or NULL_ADDRESS
        to = to or NULL_ADDRESS

        # Make sure refund receiver is set to 0x0 so that the contract refunds the gas costs to tx.origin
        if not self._check_refund_receiver(refund_receiver):
            raise InvalidRefundReceiver(refund_receiver)

        self._check_safe_gas_price(gas_token, gas_price)

        # Make sure proxy contract is ours
        if not self.safe_service.check_proxy_code(safe_address):
            raise InvalidProxyContract(safe_address)

        # Make sure master copy is valid
        if not self.safe_service.check_master_copy(safe_address):
            raise InvalidMasterCopyAddress

        # Check enough funds to pay for the gas
        if not self.safe_service.check_funds_for_tx_gas(safe_address, safe_tx_gas, data_gas, gas_price, gas_token):
            raise NotEnoughFundsForMultisigTx

        threshold = self.safe_service.retrieve_threshold(safe_address)
        number_signatures = len(signatures) // 65  # One signature = 65 bytes
        if number_signatures < threshold:
            raise SignaturesNotFound('Need at least %d signatures' % threshold)

        safe_tx_gas_estimation = self.safe_service.estimate_tx_gas(safe_address, to, value, data, operation)
        safe_data_gas_estimation = self.safe_service.estimate_tx_data_gas(safe_address, to, value, data, operation,
                                                                          gas_token, safe_tx_gas_estimation)
        if safe_tx_gas < safe_tx_gas_estimation or data_gas < safe_data_gas_estimation:
            raise InvalidGasEstimation("Gas should be at least equal to safe-tx-gas=%d and data-gas=%d. Current is "
                                       "safe-tx-gas=%d and data-gas=%d" %
                                       (safe_tx_gas_estimation, safe_data_gas_estimation, safe_tx_gas, data_gas))

        # We use fast tx gas price, if not txs could be stuck
        tx_gas_price = self.gas_station.get_gas_prices().fast
        tx_sender_private_key = self.tx_sender_account.privateKey
        tx_sender_address = Account.privateKeyToAccount(tx_sender_private_key).address

        safe_tx = self.safe_service.build_multisig_tx(
            safe_address,
            to,
            value,
            data,
            operation,
            safe_tx_gas,
            data_gas,
            gas_price,
            gas_token,
            refund_receiver,
            signatures,
            safe_nonce=safe_nonce,
            safe_version=self.safe_service.retrieve_version(safe_address)
        )

        if safe_tx.signers != safe_tx.sorted_signers:
            raise SignaturesNotSorted('Safe-tx-hash=%s - Signatures are not sorted by owner: %s' %
                                      (safe_tx.safe_tx_hash, safe_tx.signers))

        safe_tx.call(tx_sender_address=tx_sender_address, block_identifier=block_identifier)

        with self.redis.lock('locks:send-multisig-tx:%s' % self.tx_sender_account.address, timeout=60 * 2):
            nonce_key = '%s:nonce' % self.tx_sender_account.address
            tx_nonce = self.redis.incr(nonce_key)
            if tx_nonce == 1:
                tx_nonce = self.ethereum_client.get_nonce_for_account(self.tx_sender_account.address)
                self.redis.set(nonce_key, tx_nonce)
            try:
                tx_hash, tx = safe_tx.execute(tx_sender_private_key, tx_gas=tx_gas, tx_gas_price=tx_gas_price,
                                              tx_nonce=tx_nonce, block_identifier=block_identifier)
                return tx_hash, safe_tx.tx_hash, tx
            except Exception as e:
                self.redis.delete(nonce_key)
                raise e
