from datetime import timedelta
from logging import getLogger
from typing import Any, Dict, List, NamedTuple, Optional, Set, Tuple

from django.db import IntegrityError
from django.db.models import Q
from django.utils import timezone

from eth_account import Account
from packaging.version import Version
from redis import Redis
from web3.exceptions import BadFunctionCallOutput

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.safe import ProxyFactory, Safe
from gnosis.safe.exceptions import SafeServiceException
from gnosis.safe.signatures import signatures_to_bytes

from safe_relay_service.gas_station.gas_station import (GasStation,
                                                        GasStationProvider)
from safe_relay_service.tokens.models import Token
from safe_relay_service.tokens.price_oracles import CannotGetTokenPriceFromApi

from ..models import EthereumBlock, EthereumTx, SafeContract, SafeMultisigTx
from ..repositories.redis_repository import EthereumNonceLock, RedisRepository

logger = getLogger(__name__)


class TransactionServiceException(Exception):
    pass


class SafeDoesNotExist(TransactionServiceException):
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


class TransactionEstimationWithNonce(NamedTuple):
    safe_tx_gas: int
    base_gas: int  # For old versions it will equal to `data_gas`
    data_gas: int  # DEPRECATED
    operational_gas: int  # DEPRECATED
    gas_price: int
    gas_token: str
    last_used_nonce: int


class TransactionGasTokenEstimation(NamedTuple):
    base_gas: int  # For old versions it will equal to `data_gas`
    gas_price: int
    gas_token: str


class TransactionEstimationWithNonceAndGasTokens(NamedTuple):
    last_used_nonce: int
    safe_tx_gas: int
    operational_gas: int  # DEPRECATED
    estimations: List[TransactionGasTokenEstimation]


class TransactionServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            cls.instance = TransactionService(GasStationProvider(),
                                              EthereumClientProvider(),
                                              RedisRepository().redis,
                                              settings.SAFE_VALID_CONTRACT_ADDRESSES,
                                              settings.SAFE_PROXY_FACTORY_ADDRESS,
                                              settings.SAFE_TX_SENDER_PRIVATE_KEY)
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class TransactionService:
    def __init__(self, gas_station: GasStation, ethereum_client: EthereumClient, redis: Redis,
                 safe_valid_contract_addresses: Set[str], proxy_factory_address: str, tx_sender_private_key: str):
        self.gas_station = gas_station
        self.ethereum_client = ethereum_client
        self.redis = redis
        self.safe_valid_contract_addresses = safe_valid_contract_addresses
        self.proxy_factory = ProxyFactory(proxy_factory_address, self.ethereum_client)
        self.tx_sender_account = Account.from_key(tx_sender_private_key)

    @staticmethod
    def _check_refund_receiver(refund_receiver: str) -> bool:
        """
        We only support tx.origin as refund receiver right now
        In the future we can also accept transactions where it is set to our service account to receive the payments.
        This would prevent that anybody can front-run our service
        """
        return refund_receiver == NULL_ADDRESS

    @staticmethod
    def _is_valid_gas_token(address: Optional[str]) -> float:
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
            logger.warning('Cannot retrieve gas token from db: Gas token %s not valid', address)
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

        minimum_accepted_gas_price = self._get_minimum_gas_price()
        if gas_token and gas_token != NULL_ADDRESS:
            try:
                gas_token_model = Token.objects.get(address=gas_token, gas=True)
                estimated_gas_price = gas_token_model.calculate_gas_price(minimum_accepted_gas_price)
                if safe_gas_price < estimated_gas_price:
                    raise GasPriceTooLow('Required gas-price>=%d to use gas-token' % estimated_gas_price)
                # We use gas station tx gas price. We cannot use internal tx's because is calculated
                # based on the gas token
            except Token.DoesNotExist:
                logger.warning('Cannot retrieve gas token from db: Gas token %s not valid', gas_token)
                raise InvalidGasToken('Gas token %s not valid' % gas_token)
        else:
            if safe_gas_price < minimum_accepted_gas_price:
                raise GasPriceTooLow('Required gas-price>=%d' % minimum_accepted_gas_price)
        return True

    def _estimate_tx_gas_price(self, gas_token: Optional[str] = None):
        gas_price_fast = self._get_configured_gas_price()
        if gas_token and gas_token != NULL_ADDRESS:
            try:
                gas_token_model = Token.objects.get(address=gas_token, gas=True)
                return gas_token_model.calculate_gas_price(gas_price_fast)
            except Token.DoesNotExist:
                raise InvalidGasToken('Gas token %s not found' % gas_token)
        else:
            return gas_price_fast

    def _get_configured_gas_price(self) -> int:
        """
        :return: Gas price for txs
        """
        return self.gas_station.get_gas_prices().standard

    def _get_last_used_nonce(self, safe_address: str) -> Optional[int]:
        safe = Safe(safe_address, self.ethereum_client)
        last_used_nonce = SafeMultisigTx.objects.get_last_nonce_for_safe(safe_address)
        try:
            last_used_nonce = last_used_nonce or (safe.retrieve_nonce() - 1)
            if last_used_nonce < 0:  # There's no last_used_nonce
                last_used_nonce = None
            return last_used_nonce
        except BadFunctionCallOutput:  # If Safe does not exist
            raise SafeDoesNotExist(f'Safe={safe_address} does not exist')

    def _get_minimum_gas_price(self) -> int:
        """
        :return: Minimum gas price accepted for txs set by the user
        """
        return self.gas_station.get_gas_prices().safe_low

    def estimate_tx(self, safe_address: str, to: str, value: int, data: str, operation: int,
                    gas_token: Optional[str]) -> TransactionEstimationWithNonce:
        """
        :return: TransactionEstimation with costs and last used nonce of safe
        :raises: InvalidGasToken: If Gas Token is not valid
        """
        if not self._is_valid_gas_token(gas_token):
            raise InvalidGasToken(gas_token)

        last_used_nonce = self._get_last_used_nonce(safe_address)
        safe = Safe(safe_address, self.ethereum_client)
        safe_tx_gas = safe.estimate_tx_gas(to, value, data, operation)
        safe_tx_base_gas = safe.estimate_tx_base_gas(to, value, data, operation, gas_token, safe_tx_gas)

        # For Safe contracts v1.0.0 operational gas is not used (`base_gas` has all the related costs already)
        safe_version = safe.retrieve_version()
        if Version(safe_version) >= Version('1.0.0'):
            safe_tx_operational_gas = 0
        else:
            safe_tx_operational_gas = safe.estimate_tx_operational_gas(len(data) if data else 0)

        # Can throw RelayServiceException
        gas_price = self._estimate_tx_gas_price(gas_token)
        return TransactionEstimationWithNonce(safe_tx_gas, safe_tx_base_gas, safe_tx_base_gas, safe_tx_operational_gas,
                                              gas_price, gas_token or NULL_ADDRESS, last_used_nonce)

    def estimate_tx_for_all_tokens(self, safe_address: str, to: str, value: int, data: str,
                                   operation: int) -> TransactionEstimationWithNonceAndGasTokens:
        safe = Safe(safe_address, self.ethereum_client)
        last_used_nonce = self._get_last_used_nonce(safe_address)
        safe_tx_gas = safe.estimate_tx_gas(to, value, data, operation)

        safe_version = safe.retrieve_version()
        if Version(safe_version) >= Version('1.0.0'):
            safe_tx_operational_gas = 0
        else:
            safe_tx_operational_gas = safe.estimate_tx_operational_gas(len(data) if data else 0)

        # Calculate `base_gas` for ether and calculate for tokens using the ether token price
        ether_safe_tx_base_gas = safe.estimate_tx_base_gas(to, value, data, operation, NULL_ADDRESS, safe_tx_gas)
        gas_price = self._estimate_tx_gas_price(NULL_ADDRESS)
        gas_token_estimations = [TransactionGasTokenEstimation(ether_safe_tx_base_gas, gas_price, NULL_ADDRESS)]
        token_gas_difference = 50000  # 50K gas more expensive than ether
        for token in Token.objects.gas_tokens():
            try:
                gas_price = self._estimate_tx_gas_price(token.address)
                gas_token_estimations.append(
                    TransactionGasTokenEstimation(ether_safe_tx_base_gas + token_gas_difference,
                                                  gas_price, token.address)
                )
            except CannotGetTokenPriceFromApi:
                logger.error('Cannot get price for token=%s', token.address)

        return TransactionEstimationWithNonceAndGasTokens(last_used_nonce, safe_tx_gas, safe_tx_operational_gas,
                                                          gas_token_estimations)

    def create_multisig_tx(self,
                           safe_address: str,
                           to: str,
                           value: int,
                           data: bytes,
                           operation: int,
                           safe_tx_gas: int,
                           base_gas: int,
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

        logger.info('create_multisig_tx called for safe=%s and nonce=%s', safe_address, nonce)
        safe_contract, _ = SafeContract.objects.get_or_create(address=safe_address,
                                                              defaults={'master_copy': NULL_ADDRESS})
        created = timezone.now()

        if SafeMultisigTx.objects.filter(safe=safe_contract, nonce=nonce).exists():
            raise SafeMultisigTxExists(f'Tx with nonce={nonce} for safe={safe_address} already exists in DB. Skipping TX.')

        signature_pairs = [(s['v'], s['r'], s['s']) for s in signatures]
        signatures_packed = signatures_to_bytes(signature_pairs)

        logger.info('create_multisig_tx executing tx for safe=%s and nonce=%s', safe_address, nonce)
        try:
            tx_hash, safe_tx_hash, tx = self._send_multisig_tx(
                safe_address,
                to,
                value,
                data,
                operation,
                safe_tx_gas,
                base_gas,
                gas_price,
                gas_token,
                refund_receiver,
                nonce,
                signatures_packed
            )
        except SafeServiceException as exc:
            raise TransactionServiceException(str(exc)) from exc

        ethereum_tx = EthereumTx.objects.create_from_tx(tx, tx_hash)

        # Fix race conditions for tx being created at the same time
        try:
            return SafeMultisigTx.objects.create(
                created=created,
                safe=safe_contract,
                ethereum_tx=ethereum_tx,
                to=to,
                value=value,
                data=data,
                operation=operation,
                safe_tx_gas=safe_tx_gas,
                data_gas=base_gas,
                gas_price=gas_price,
                gas_token=None if gas_token == NULL_ADDRESS else gas_token,
                refund_receiver=refund_receiver,
                nonce=nonce,
                signatures=signatures_packed,
                safe_tx_hash=safe_tx_hash,
            )
        except IntegrityError as exc:
            raise SafeMultisigTxExists(f'Tx with nonce={nonce} for safe={safe_address} already exists in DB. TX was sent') from exc

    def _send_multisig_tx(self,
                          safe_address: str,
                          to: str,
                          value: int,
                          data: bytes,
                          operation: int,
                          safe_tx_gas: int,
                          base_gas: int,
                          gas_price: int,
                          gas_token: str,
                          refund_receiver: str,
                          safe_nonce: int,
                          signatures: bytes,
                          tx_gas=None,
                          block_identifier='latest') -> Tuple[bytes, bytes, Dict[str, Any]]:
        """
        This function calls the `send_multisig_tx` of the Safe, but has some limitations to prevent abusing
        the relay
        :return: Tuple(tx_hash, safe_tx_hash, tx)
        :raises: InvalidMultisigTx: If user tx cannot go through the Safe
        """

        safe = Safe(safe_address, self.ethereum_client)
        data = data or b''
        gas_token = gas_token or NULL_ADDRESS
        refund_receiver = refund_receiver or NULL_ADDRESS
        to = to or NULL_ADDRESS

        # Make sure refund receiver is set to 0x0 so that the contract refunds the gas costs to tx.origin
        if not self._check_refund_receiver(refund_receiver):
            raise InvalidRefundReceiver(refund_receiver)

        self._check_safe_gas_price(gas_token, gas_price)

        # Make sure proxy contract is ours
        if not self.proxy_factory.check_proxy_code(safe_address):
            raise InvalidProxyContract(safe_address)

        # Make sure master copy is valid
        safe_master_copy_address = safe.retrieve_master_copy_address()
        if safe_master_copy_address not in self.safe_valid_contract_addresses:
            raise InvalidMasterCopyAddress(safe_master_copy_address)

        # Check enough funds to pay for the gas
        if not safe.check_funds_for_tx_gas(safe_tx_gas, base_gas, gas_price, gas_token):
            raise NotEnoughFundsForMultisigTx

        threshold = safe.retrieve_threshold()
        number_signatures = len(signatures) // 65  # One signature = 65 bytes
        if number_signatures < threshold:
            raise SignaturesNotFound('Need at least %d signatures' % threshold)

        safe_tx_gas_estimation = safe.estimate_tx_gas(to, value, data, operation)
        safe_base_gas_estimation = safe.estimate_tx_base_gas(to, value, data, operation, gas_token,
                                                             safe_tx_gas_estimation)
        if safe_tx_gas < safe_tx_gas_estimation or base_gas < safe_base_gas_estimation:
            raise InvalidGasEstimation("Gas should be at least equal to safe-tx-gas=%d and base-gas=%d. Current is "
                                       "safe-tx-gas=%d and base-gas=%d" %
                                       (safe_tx_gas_estimation, safe_base_gas_estimation, safe_tx_gas, base_gas))

        # Use user provided gasPrice for TX if more than our stardard gas price
        standard_gas = self._get_configured_gas_price()
        if gas_price > standard_gas :
            tx_gas_price = gas_price
        else:
            tx_gas_price = standard_gas

        tx_sender_private_key = self.tx_sender_account.key
        tx_sender_address = Account.from_key(tx_sender_private_key).address

        safe_tx = safe.build_multisig_tx(
            to,
            value,
            data,
            operation,
            safe_tx_gas,
            base_gas,
            gas_price,
            gas_token,
            refund_receiver,
            signatures,
            safe_nonce=safe_nonce,
            safe_version=safe.retrieve_version()
        )

        if safe_tx.signers != safe_tx.sorted_signers:
            raise SignaturesNotSorted('Safe-tx-hash=%s - Signatures are not sorted by owner: %s' %
                                      (safe_tx.safe_tx_hash.hex(), safe_tx.signers))

        safe_tx.call(tx_sender_address=tx_sender_address, block_identifier=block_identifier)

        logger.info('_send_multisig_tx about to execute tx for safe=%s and nonce=%s', safe_address, safe_nonce)
        with EthereumNonceLock(self.redis, self.ethereum_client, self.tx_sender_account.address,
                               timeout=60 * 2) as tx_nonce:
            logger.info('_send_multisig_tx executing tx for safe=%s and nonce=%s', safe_address, safe_nonce)
            tx_hash, tx = safe_tx.execute(tx_sender_private_key, tx_gas=tx_gas, tx_gas_price=tx_gas_price,
                                          tx_nonce=tx_nonce, block_identifier=block_identifier)
            return tx_hash, safe_tx.safe_tx_hash, tx

    def get_pending_multisig_transactions(self, older_than: int) -> List[SafeMultisigTx]:
        """
        Get multisig txs that have not been mined after `older_than` seconds
        :param older_than: Time in seconds for a tx to be considered pending, if 0 all will be returned
        """
        return SafeMultisigTx.objects.filter(
            Q(ethereum_tx__block=None) | Q(ethereum_tx=None)
        ).filter(
            created__lte=timezone.now() - timedelta(seconds=older_than),
        )

    # TODO Refactor and test
    def create_or_update_ethereum_tx(self, tx_hash: str) -> EthereumTx:
        try:
            ethereum_tx = EthereumTx.objects.get(tx_hash=tx_hash)
            if ethereum_tx.block is None:
                tx_receipt = self.ethereum_client.get_transaction_receipt(tx_hash)
                if tx_receipt:
                    ethereum_tx.block = self.get_or_create_ethereum_block(tx_receipt.blockNumber)
                    ethereum_tx.gas_used = tx_receipt.gasUsed
                    ethereum_tx.save()
            return ethereum_tx
        except EthereumTx.DoesNotExist:
            tx = self.ethereum_client.get_transaction(tx_hash)
            if tx:
                if tx_receipt:
                    tx_receipt = self.ethereum_client.get_transaction_receipt(tx_hash)
                    ethereum_block = self.get_or_create_ethereum_block(tx_receipt.blockNumber)
                    return EthereumTx.objects.create_from_tx(tx, tx_hash, tx_receipt.gasUsed, ethereum_block)
                return EthereumTx.objects.create_from_tx(tx, tx_hash)

    # TODO Refactor and test
    def get_or_create_ethereum_block(self, block_number: int):
        try:
            return EthereumBlock.objects.get(number=block_number)
        except EthereumBlock.DoesNotExist:
            block = self.ethereum_client.get_block(block_number)
            return EthereumBlock.objects.create_from_block(block)
