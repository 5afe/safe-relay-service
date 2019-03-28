from logging import getLogger
from typing import Dict, List, NamedTuple, Tuple, Union

from eth_account import Account
from redis import Redis

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.safe.exceptions import GasPriceTooLow, SafeServiceException
from gnosis.safe.safe_service import SafeService, SafeServiceProvider

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


class SafeMultisigTxError(TransactionServiceException):
    pass


class NotEnoughFundsForMultisigTx(TransactionServiceException):
    pass


class InvalidMasterCopyAddress(TransactionServiceException):
    pass


class InvalidProxyContract(TransactionServiceException):
    pass


class InvalidRefundReceiver(TransactionServiceException):
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
                                              settings.SAFE_TX_SENDER_PRIVATE_KEY)
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class TransactionService:
    def __init__(self, safe_service: SafeService, gas_station: GasStation, ethereum_client: EthereumClient,
                 redis: Redis, tx_sender_private_key: str):
        self.safe_service = safe_service
        self.gas_station = gas_station
        self.ethereum_client = ethereum_client
        self.redis = redis
        self.tx_sender_account = Account.privateKeyToAccount(tx_sender_private_key)

    @staticmethod
    def _check_refund_receiver(refund_receiver: str) -> bool:
        """
        We only support tx.origin as refund receiver right now
        In the future we can also accept transactions where it is set to our service account to receive the payments.
        This would prevent that anybody can front-run our service
        """
        return refund_receiver == NULL_ADDRESS

    def _is_valid_gas_token(self, address: str) -> float:
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

    def _estimate_tx_gas_price(self, gas_token: Union[str, None]=None):
        gas_token = gas_token or NULL_ADDRESS
        gas_price_fast = self.gas_station.get_gas_prices().fast

        if gas_token != NULL_ADDRESS:
            try:
                gas_token_model = Token.objects.get(address=gas_token, gas=True)
                return gas_token_model.calculate_gas_price(gas_price_fast)
            except Token.DoesNotExist:
                raise InvalidGasToken('Gas token %s not found' % gas_token)
        else:
            return gas_price_fast

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
        :raises: SafeMultisigTxError: If Safe Tx is not valid (not sorted owners, bad signature, bad nonce...)
        """

        if SafeMultisigTx.objects.filter(safe=safe_address, nonce=nonce).exists():
            raise SafeMultisigTxExists('Tx with nonce=%d for safe=%s already exists in DB' % (nonce, safe_address))

        if not self._is_valid_gas_token(gas_token):
            raise InvalidGasToken(gas_token)

        safe_version = self.safe_service.retrieve_version(safe_address)
        signature_pairs = [(s['v'], s['r'], s['s']) for s in signatures]
        signatures_packed = self.safe_service.signatures_to_bytes(signature_pairs)
        safe_tx_hash = self.safe_service.get_hash_for_safe_tx(safe_address, to, value, data,
                                                              operation, safe_tx_gas, data_gas, gas_price,
                                                              gas_token, refund_receiver, nonce,
                                                              safe_version=safe_version)

        owners = [EthereumClient.get_signing_address(safe_tx_hash,
                                                     signature['v'],
                                                     signature['r'],
                                                     signature['s']) for signature in signatures]

        signature_pairs = [(s['v'], s['r'], s['s']) for s in signatures]
        if not SafeService.check_hash(safe_tx_hash, SafeService.signatures_to_bytes(signature_pairs), owners):
            raise SignaturesNotSorted('Signatures are not sorted by owner: %s' % owners)

        try:
            tx_hash, tx = self.send_multisig_tx(
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
                signatures_packed
            )
        except (SafeServiceException, TransactionServiceException) as exc:
            raise SafeMultisigTxError(str(exc)) from exc

        safe_contract = SafeContract.objects.get(address=safe_address)

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
            tx_hash=tx_hash.hex(),
            tx_mined=False
        )

    def estimate_tx_cost(self, safe_address: str, to: str, value: int, data: str, operation: int,
                         gas_token: Union[str, None]) -> TransactionEstimation:
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

    def send_multisig_tx(self,
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
                         signatures: bytes,
                         tx_sender_private_key=None,
                         tx_gas=None,
                         block_identifier='pending') -> Tuple[str, any]:
        """
        This function calls the `send_multisig_tx` of the SafeService, but has some limitations to prevent abusing
        the relay
        :return: Tuple(tx_hash, tx)
        :raises: InvalidMultisigTx: If user tx cannot go through the Safe
        """

        data = data or b''
        gas_token = gas_token or NULL_ADDRESS
        refund_receiver = refund_receiver or NULL_ADDRESS
        to = to or NULL_ADDRESS

        if gas_price < 1:
            raise RefundMustBeEnabled('Tx internal gas price cannot be 0 or less')

        # Make sure refund receiver is set to 0x0 so that the contract refunds the gas costs to tx.origin
        if not self._check_refund_receiver(refund_receiver):
            raise InvalidRefundReceiver(refund_receiver)

        # Make sure proxy contract is ours
        # TODO Test this
        if not self.safe_service.check_proxy_code(safe_address):
            raise InvalidProxyContract(safe_address)

        # Make sure master copy is valid
        # TODO Test this
        if not self.safe_service.check_master_copy(safe_address):
            raise InvalidMasterCopyAddress

        # Check enough funds to pay for the gas
        if not self.safe_service.check_funds_for_tx_gas(safe_address, safe_tx_gas, data_gas, gas_price, gas_token):
            raise NotEnoughFundsForMultisigTx

        threshold = self.safe_service.retrieve_threshold(safe_address)
        number_signatures = len(signatures) // 65  # One signature = 65 bytes
        if number_signatures < threshold:
            raise SignaturesNotFound('Need at least %d signatures' % threshold)

        # If gas_token is specified, we see if the `gas_price` matches the current token value and use as the
        # external tx gas the fast gas price from the gas station.
        # If not, we just use the internal tx gas_price for the gas_price
        # Gas price must be at least >= standard gas price
        current_gas_prices = self.gas_station.get_gas_prices()
        current_fast_gas_price = current_gas_prices.fast
        current_standard_gas_price = current_gas_prices.standard

        # TODO Maybe refactor this
        if gas_token != NULL_ADDRESS:
            try:
                gas_token_model = Token.objects.get(address=gas_token, gas=True)
                estimated_gas_price = gas_token_model.calculate_gas_price(current_standard_gas_price)
                if gas_price < estimated_gas_price:
                    raise GasPriceTooLow('Required gas-price>=%d to use gas-token' % estimated_gas_price)
                # We use gas station tx gas price. We cannot use internal tx's because is calculated
                # based on the gas token
            except Token.DoesNotExist:
                raise InvalidGasToken('Gas token %s not valid' % gas_token)
        else:
            if gas_price < current_standard_gas_price:
                raise GasPriceTooLow('Required gas-price>=%d' % current_standard_gas_price)

        # We use fast tx gas price, if not txs could we stuck
        tx_gas_price = current_fast_gas_price

        tx_sender_private_key = tx_sender_private_key or self.tx_sender_account.privateKey
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
        )

        safe_tx.call(tx_sender_address=tx_sender_address, block_identifier=block_identifier)

        with self.redis.lock('locks:send-multisig-tx:%s' % self.tx_sender_account.address, timeout=60 * 2):
            nonce_key = '%s:nonce' % self.tx_sender_account.address
            tx_nonce = self.redis.incr(nonce_key)
            if tx_nonce == 1:
                tx_nonce = self.ethereum_client.get_nonce_for_account(safe_address)

            try:
                return safe_tx.execute(tx_sender_private_key, tx_gas=tx_gas, tx_gas_price=tx_gas_price, tx_nonce=tx_nonce,
                                       block_identifier=block_identifier)
            except Exception as e:
                self.redis.delete(nonce_key)
                raise e
