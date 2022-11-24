from logging import getLogger
from typing import Any, Dict, List, NamedTuple, Optional, Set, Tuple

from django.conf import settings
from django.db import IntegrityError
from django.utils import timezone

from eth_account import Account
from eth_account.signers.local import LocalAccount
from packaging.version import Version
from redis import Redis
from web3.exceptions import BadFunctionCallOutput

from gnosis.eth import EthereumClient, EthereumClientProvider, InvalidNonce, TxSpeed
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.safe import ProxyFactory, Safe
from gnosis.safe.exceptions import InvalidMultisigTx, SafeServiceException
from gnosis.safe.signatures import signatures_to_bytes

from safe_relay_service.gas_station.gas_station import GasStation, GasStationProvider
from safe_relay_service.tokens.models import Token
from safe_relay_service.tokens.price_oracles import CannotGetTokenPriceFromApi
from safe_relay_service.relay.services.circles_service import CirclesService

from ..models import (
    BannedSigner,
    EthereumBlock,
    EthereumTx,
    SafeContract,
    SafeMultisigTx,
)
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


class InvalidOwners(TransactionServiceException):
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


class SignerIsBanned(TransactionServiceException):
    pass


class TransactionEstimationWithNonce(NamedTuple):
    safe_tx_gas: int
    base_gas: int  # For old versions it will equal to `data_gas`
    data_gas: int  # DEPRECATED
    operational_gas: int  # DEPRECATED
    gas_price: int
    gas_token: str
    last_used_nonce: int
    refund_receiver: str


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
        if not hasattr(cls, "instance"):
            from django.conf import settings

            cls.instance = TransactionService(
                GasStationProvider(),
                EthereumClientProvider(),
                RedisRepository().redis,
                settings.SAFE_VALID_CONTRACT_ADDRESSES,
                settings.SAFE_PROXY_FACTORY_ADDRESS,
                settings.SAFE_PROXY_FACTORY_V1_0_0_ADDRESS,
                settings.SAFE_TX_SENDER_PRIVATE_KEY,
            )
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class TransactionService:
    def __init__(
        self,
        gas_station: GasStation,
        ethereum_client: EthereumClient,
        redis: Redis,
        safe_valid_contract_addresses: Set[str],
        proxy_factory_address: str,
        proxy_factory_crc_address: str,
        tx_sender_private_key: str,
    ):
        self.gas_station = gas_station
        self.ethereum_client = ethereum_client
        self.redis = redis
        self.safe_valid_contract_addresses = safe_valid_contract_addresses
        self.proxy_factory = ProxyFactory(proxy_factory_address, self.ethereum_client)
        self.proxy_factory_crc = ProxyFactory(
            proxy_factory_crc_address, self.ethereum_client
        )
        self.tx_sender_account: LocalAccount = Account.from_key(tx_sender_private_key)

    def _check_refund_receiver(self, refund_receiver: str) -> bool:
        """
        Support tx.origin or relay tx sender as refund receiver.
        This would prevent that anybody can front-run our service

        :param refund_receiver: Payment refund receiver as Ethereum checksummed address
        :return: True if refund_receiver is ok, False otherwise
        """
        return refund_receiver in (NULL_ADDRESS, self.tx_sender_account.address)

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
            # @TODO: Fetch valid Tokens from database instead
            ethereum_client = EthereumClientProvider()
            return CirclesService(ethereum_client).is_circles_token(address)
        except Token.DoesNotExist:
            logger.warning(
                "Cannot retrieve gas token from db: Gas token %s not valid", address
            )
            return False

    def _check_safe_gas_price(
        self, gas_token: Optional[str], safe_gas_price: int
    ) -> bool:
        """
        Check that `safe_gas_price` is not too low, so that the relay gets a full refund
        for the tx. Gas_price must be always > 0, if not refunding would be disabled
        If a `gas_token` is used we need to calculate the `gas_price` in Eth
        Gas price must be at least >= _minimum_gas_price_ > 0

        :param gas_token: Address of token is used, `NULL_ADDRESS` or `None` if it's ETH
        :return:
        :exception GasPriceTooLow
        :exception InvalidGasToken
        """
        if safe_gas_price < 1:
            raise RefundMustBeEnabled(
                "Tx internal gas price cannot be 0 or less, it was %d" % safe_gas_price
            )

        minimum_accepted_gas_price = self._get_minimum_gas_price()

        if gas_token and gas_token != NULL_ADDRESS:
            estimated_gas_price = self._estimate_tx_gas_price(
                self._get_minimum_gas_price(), gas_token=gas_token
            )
            if safe_gas_price < estimated_gas_price:
                raise GasPriceTooLow(
                    "Required gas-price>=%d to use gas-token" % estimated_gas_price
                )
            # We use gas station tx gas price. We cannot use internal tx's because is calculated
            # based on the gas token
        else:
            if safe_gas_price < minimum_accepted_gas_price:
                raise GasPriceTooLow(
                    "Required gas-price>=%d" % minimum_accepted_gas_price
                )
        return True

    def _estimate_tx_gas_price(
        self, base_gas_price: int, gas_token: Optional[str] = None
    ) -> int:
        if gas_token and gas_token != NULL_ADDRESS:
            return CirclesService(self.ethereum_client).get_gas_price()
        else:
            estimated_gas_price = base_gas_price

        # FIXME Remove 2 / 3, workaround to prevent frontrunning
        return int(estimated_gas_price)

    def _get_configured_gas_price(self) -> int:
        """
        :return: Gas price for txs
        """
        return self.gas_station.get_gas_prices().fast

    def _get_minimum_gas_price(self) -> int:
        """
        :return: Minimum gas price accepted for txs set by the user
        """
        return self.gas_station.get_gas_prices().standard

    def get_last_used_nonce(self, safe_address: str) -> Optional[int]:
        safe = Safe(safe_address, self.ethereum_client)
        last_used_nonce = SafeMultisigTx.objects.get_last_nonce_for_safe(safe_address)
        last_used_nonce = last_used_nonce if last_used_nonce is not None else -1
        try:
            blockchain_nonce = safe.retrieve_nonce()
            last_used_nonce = max(last_used_nonce, blockchain_nonce - 1)
            if last_used_nonce < 0:  # There's no last_used_nonce
                last_used_nonce = None
            return last_used_nonce
        except BadFunctionCallOutput:  # If Safe does not exist
            raise SafeDoesNotExist(f"Safe={safe_address} does not exist")

    def estimate_tx(
        self,
        safe_address: str,
        to: str,
        value: int,
        data: bytes,
        operation: int,
        gas_token: Optional[str],
    ) -> TransactionEstimationWithNonce:
        """
        :return: TransactionEstimation with costs using the provided gas token and last used nonce of the Safe
        :raises: InvalidGasToken: If Gas Token is not valid
        """
        if not self._is_valid_gas_token(gas_token):
            raise InvalidGasToken(gas_token)

        last_used_nonce = self.get_last_used_nonce(safe_address)
        safe = Safe(safe_address, self.ethereum_client)
        safe_tx_gas = safe.estimate_tx_gas(to, value, data, operation)
        safe_tx_base_gas = safe.estimate_tx_base_gas(
            to, value, data, operation, gas_token, safe_tx_gas
        )

        # For Safe contracts v1.0.0 operational gas is not used (`base_gas` has all the related costs already)
        safe_version = safe.retrieve_version()
        if Version(safe_version) >= Version("1.0.0"):
            safe_tx_operational_gas = 0
        else:
            safe_tx_operational_gas = safe.estimate_tx_operational_gas(
                len(data) if data else 0
            )

        # Can throw RelayServiceException
        gas_price = self._estimate_tx_gas_price(
            self._get_configured_gas_price(), gas_token
        )
        return TransactionEstimationWithNonce(
            safe_tx_gas,
            safe_tx_base_gas,
            safe_tx_base_gas,
            safe_tx_operational_gas,
            gas_price,
            gas_token or NULL_ADDRESS,
            last_used_nonce,
            self.tx_sender_account.address,
        )

    def estimate_tx_for_all_tokens(
        self, safe_address: str, to: str, value: int, data: bytes, operation: int
    ) -> TransactionEstimationWithNonceAndGasTokens:
        """
        :return: TransactionEstimation with costs using ether and every gas token supported by the service,
        with the last used nonce of the Safe
        :raises: InvalidGasToken: If Gas Token is not valid
        """
        safe = Safe(safe_address, self.ethereum_client)
        last_used_nonce = self.get_last_used_nonce(safe_address)
        safe_tx_gas = safe.estimate_tx_gas(to, value, data, operation)

        safe_version = safe.retrieve_version()
        if Version(safe_version) >= Version("1.0.0"):
            safe_tx_operational_gas = 0
        else:
            safe_tx_operational_gas = safe.estimate_tx_operational_gas(
                len(data) if data else 0
            )

        # Calculate `base_gas` for ether and calculate for tokens using the ether token price
        ether_safe_tx_base_gas = safe.estimate_tx_base_gas(
            to, value, data, operation, NULL_ADDRESS, safe_tx_gas
        )
        base_gas_price = self._get_configured_gas_price()
        gas_price = self._estimate_tx_gas_price(base_gas_price, NULL_ADDRESS)
        gas_token_estimations = [
            TransactionGasTokenEstimation(
                ether_safe_tx_base_gas, gas_price, NULL_ADDRESS
            )
        ]
        token_gas_difference = 50000  # 50K gas more expensive than ether
        for token in Token.objects.gas_tokens():
            try:
                gas_price = self._estimate_tx_gas_price(base_gas_price, token.address)
                gas_token_estimations.append(
                    TransactionGasTokenEstimation(
                        ether_safe_tx_base_gas + token_gas_difference,
                        gas_price,
                        token.address,
                    )
                )
            except CannotGetTokenPriceFromApi:
                logger.error("Cannot get price for token=%s", token.address)

        return TransactionEstimationWithNonceAndGasTokens(
            last_used_nonce, safe_tx_gas, safe_tx_operational_gas, gas_token_estimations
        )

    def estimate_circles_hub_method(
        self, data: bytes, safe_address: str, gas_token: str = NULL_ADDRESS
    ) -> int:
        """
        Estimates gas costs of Hub contract method
        :param data:
        :param safe_address:
        :param gas_token:
        """
        value = 0
        operation = 0
        transaction_estimation = self.estimate_tx(
            safe_address,
            settings.CIRCLES_HUB_ADDRESS,
            value,
            data,
            operation,
            gas_token,
        )
        return int(
            (
                (transaction_estimation.safe_tx_gas * 64 / 63)
                + transaction_estimation.base_gas
                + 500
            )
            * transaction_estimation.gas_price
        )

    def estimate_circles_signup_tx(
        self, safe_address: str, gas_token: str = NULL_ADDRESS
    ) -> int:
        """
        Estimates gas costs of Circles token deployment method
        :param safe_address:
        :param gas_token:
        """
        # Tx data from Circles Hub contract `signup` method
        data = "0xb7bc0f73"
        return 1800000000000000

    def estimate_circles_organization_signup_tx(
        self, safe_address: str, gas_token: str = NULL_ADDRESS
    ) -> int:
        """
        Estimates gas costs of Circles organization deployment method
        :param safe_address:
        :param gas_token:
        """
        # Tx data from Circles Hub contract organizationSignup method
        data = "0x3fbd653c"
        return self.estimate_circles_hub_method(data, safe_address, gas_token)

    def create_multisig_tx(
        self,
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
        signatures: List[Dict[str, int]],
    ) -> SafeMultisigTx:
        """
        :return: Database model of SafeMultisigTx
        :raises: SafeMultisigTxExists: If Safe Multisig Tx with nonce already exists
        :raises: InvalidGasToken: If Gas Token is not valid
        :raises: TransactionServiceException: If Safe Tx is not valid (not sorted owners, bad signature, bad nonce...)
        """

        safe_contract, _ = SafeContract.objects.get_or_create(
            address=safe_address, defaults={"master_copy": NULL_ADDRESS}
        )
        created = timezone.now()

        if (
            SafeMultisigTx.objects.not_failed()
            .filter(safe=safe_contract, nonce=safe_nonce)
            .exists()
        ):
            raise SafeMultisigTxExists(
                f"Tx with safe-nonce={safe_nonce} for safe={safe_address} already exists in DB"
            )

        signature_pairs = [(s["v"], s["r"], s["s"]) for s in signatures]
        signatures_packed = signatures_to_bytes(signature_pairs)

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
                safe_nonce,
                signatures_packed,
            )
        except SafeServiceException as exc:
            raise TransactionServiceException(str(exc)) from exc

        ethereum_tx = EthereumTx.objects.create_from_tx_dict(tx, tx_hash)

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
                nonce=safe_nonce,
                signatures=signatures_packed,
                safe_tx_hash=safe_tx_hash,
            )
        except IntegrityError as exc:
            raise SafeMultisigTxExists(
                f"Tx with safe_tx_hash={safe_tx_hash.hex()} already exists in DB"
            ) from exc

    def _send_multisig_tx(
        self,
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
        block_identifier="latest",
    ) -> Tuple[bytes, bytes, Dict[str, Any]]:
        """
        This function calls the `send_multisig_tx` of the Safe, but has some limitations to prevent abusing
        the relay

        :return: Tuple(tx_hash, safe_tx_hash, tx)
        :raises: InvalidMultisigTx: If user tx cannot go through the Safe
        """

        safe = Safe(safe_address, self.ethereum_client)
        data = data or b""
        gas_token = gas_token or NULL_ADDRESS
        refund_receiver = refund_receiver or NULL_ADDRESS
        to = to or NULL_ADDRESS

        # Make sure refund receiver is set to 0x0 so that the contract refunds the gas costs to tx.origin
        if not self._check_refund_receiver(refund_receiver):
            raise InvalidRefundReceiver(refund_receiver)

        # Make sure we only pay gas fees with Circles Tokens
        if not self._is_valid_gas_token(gas_token):
            raise InvalidGasToken(gas_token)

        self._check_safe_gas_price(gas_token, gas_price)

        # Make sure proxy contract is ours (either of v1.1.1+Circles or v1.3.0)
        if not self.proxy_factory.check_proxy_code(
            safe_address
        ) and not self.proxy_factory_crc.check_proxy_code(safe_address):
            raise InvalidProxyContract(safe_address)

        # Make sure master copy is valid
        safe_master_copy_address = safe.retrieve_master_copy_address()
        if safe_master_copy_address not in self.safe_valid_contract_addresses:
            raise InvalidMasterCopyAddress(safe_master_copy_address)

        # Check enough funds to pay for the gas
        if not safe.check_funds_for_tx_gas(safe_tx_gas, base_gas, gas_price, gas_token):
            safe_balance = self.ethereum_client.get_balance(safe_address)
            logger.info("found balance %d at safe %s", safe_balance, safe_address)
            logger.info(
                "called with params: safe tx gas: %d base gas: %d gas price: %d gas token: %s",
                safe_tx_gas,
                base_gas,
                gas_price,
                gas_token,
            )
            logger.info("Looking for %d", (safe_tx_gas + base_gas) * gas_price)
            raise NotEnoughFundsForMultisigTx

        threshold = safe.retrieve_threshold()
        number_signatures = len(signatures) // 65  # One signature = 65 bytes
        if number_signatures < threshold:
            raise SignaturesNotFound("Need at least %d signatures" % threshold)

        safe_tx_gas_estimation = safe.estimate_tx_gas(to, value, data, operation)
        safe_base_gas_estimation = safe.estimate_tx_base_gas(
            to, value, data, operation, gas_token, safe_tx_gas_estimation
        )
        if safe_tx_gas < safe_tx_gas_estimation or base_gas < safe_base_gas_estimation:
            raise InvalidGasEstimation(
                "Gas should be at least equal to safe-tx-gas=%d and base-gas=%d. Current is "
                "safe-tx-gas=%d and base-gas=%d"
                % (
                    safe_tx_gas_estimation,
                    safe_base_gas_estimation,
                    safe_tx_gas,
                    base_gas,
                )
            )

        # We use fast tx gas price, if not txs could be stuck
        tx_gas_price = self._get_configured_gas_price()
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
            safe_version=safe.retrieve_version(),
        )

        owners = safe.retrieve_owners()
        signers = safe_tx.signers
        if set(signers) - set(owners):  # All the signers must be owners
            raise InvalidOwners(
                "Signers=%s are not valid owners of the safe. Owners=%s",
                safe_tx.signers,
                owners,
            )

        if signers != safe_tx.sorted_signers:
            raise SignaturesNotSorted(
                "Safe-tx-hash=%s - Signatures are not sorted by owner: %s"
                % (safe_tx.safe_tx_hash.hex(), safe_tx.signers)
            )

        if banned_signers := BannedSigner.objects.filter(address__in=signers):
            raise SignerIsBanned(f"Signers {list(banned_signers)} are banned")

        logger.info(
            "Safe=%s safe-nonce=%d Check `call()` before sending transaction",
            safe_address,
            safe_nonce,
        )
        # Set `gasLimit` for `call()`. It will use the same that it will be used later for execution
        tx_gas = safe_tx.recommended_gas()
        safe_tx.call(
            tx_sender_address=tx_sender_address,
            tx_gas=tx_gas,
            block_identifier=block_identifier,
        )
        with EthereumNonceLock(
            self.redis,
            self.ethereum_client,
            self.tx_sender_account.address,
            lock_timeout=60 * 2,
        ) as tx_nonce:
            logger.info(
                "Safe=%s safe-nonce=%d `call()` was successful",
                safe_address,
                safe_nonce,
            )
            tx_hash, tx = safe_tx.execute(
                tx_sender_private_key,
                tx_gas=tx_gas,
                tx_gas_price=tx_gas_price,
                tx_nonce=tx_nonce,
                block_identifier=block_identifier,
                eip1559_speed=TxSpeed.NORMAL,
            )
            logger.info(
                "Safe=%s, Sent transaction with nonce=%d tx-hash=%s for safe-tx-hash=%s safe-nonce=%d",
                safe_address,
                tx_nonce,
                tx_hash.hex(),
                safe_tx.safe_tx_hash.hex(),
                safe_tx.safe_nonce,
            )
            return tx_hash, safe_tx.safe_tx_hash, tx

    def resend(
        self, gas_price: int, multisig_tx: SafeMultisigTx
    ) -> Optional[EthereumTx]:
        """
        Resend transaction with `gas_price` if it's higher or equal than transaction gas price. Setting equal
        `gas_price` is allowed as sometimes a transaction can be out of the mempool but `gas_price` does not need
        to be increased when resending

        :param gas_price: New gas price for the transaction. Must be >= old gas price
        :param multisig_tx: Multisig Tx not mined to be sent again
        :return: If a new transaction is sent is returned, `None` if not
        """
        assert multisig_tx.ethereum_tx.block_id is None, "Block is present!"
        transaction_receipt = self.ethereum_client.get_transaction_receipt(
            multisig_tx.ethereum_tx_id
        )
        if transaction_receipt and transaction_receipt["blockNumber"]:
            logger.info(
                "%s tx was already mined on block %d",
                multisig_tx.ethereum_tx_id,
                transaction_receipt["blockNumber"],
            )
            return None

        # Check that transaction is still valid
        safe_tx = multisig_tx.get_safe_tx(self.ethereum_client)
        tx_gas = safe_tx.recommended_gas()
        try:
            safe_tx.call(
                tx_sender_address=self.tx_sender_account.address, tx_gas=tx_gas
            )
        except InvalidMultisigTx:
            # Maybe there's a transaction with a lower nonce that must be mined before
            # It doesn't matter, as soon as a transaction with a newer nonce is added it will be deleted
            return None

        if multisig_tx.ethereum_tx.gas_price >= gas_price:
            logger.info(
                "%s tx gas price is %d >= current gas price %d. Tx should be mined soon",
                multisig_tx.ethereum_tx_id,
                multisig_tx.ethereum_tx.gas_price,
                gas_price,
            )
            # Maybe tx was deleted from mempool, resend it
            tx_params = multisig_tx.ethereum_tx.as_tx_dict()
            raw_transaction = self.tx_sender_account.sign_transaction(tx_params)[
                "rawTransaction"
            ]
            try:
                self.ethereum_client.send_raw_transaction(raw_transaction)
            except ValueError:
                logger.warning("Error resending transaction", exc_info=True)
            return None
        safe = Safe(multisig_tx.safe_id, self.ethereum_client)
        try:
            safe_nonce = safe.retrieve_nonce()
            if safe_nonce > multisig_tx.nonce:
                logger.info(
                    "%s tx safe nonce is %d and current safe nonce is %d. Transaction is not valid anymore. Deleting",
                    multisig_tx.ethereum_tx_id,
                    multisig_tx.nonce,
                    safe_nonce,
                )
                multisig_tx.delete()  # Transaction is not valid anymore
                return None
        except (ValueError, BadFunctionCallOutput):
            logger.error(
                "Something is wrong with Safe %s, cannot retrieve nonce",
                multisig_tx.safe_id,
                exc_info=True,
            )
            return None

        logger.info(
            "%s tx gas price was %d. Resending with new gas price %d",
            multisig_tx.ethereum_tx_id,
            multisig_tx.ethereum_tx.gas_price,
            gas_price,
        )
        try:
            tx_hash, tx = safe_tx.execute(
                self.tx_sender_account.key,
                tx_gas=tx_gas,
                tx_gas_price=gas_price,
                tx_nonce=multisig_tx.ethereum_tx.nonce,
                eip1559_speed=TxSpeed.NORMAL,
            )
            logger.info(
                "Tx with old tx-hash %s was resent with a new tx-hash %s",
                multisig_tx.ethereum_tx_id,
                tx_hash.hex(),
            )
        except InvalidNonce:
            # Send transaction again with a new nonce
            with EthereumNonceLock(
                self.redis,
                self.ethereum_client,
                self.tx_sender_account.address,
                lock_timeout=60 * 2,
            ) as tx_nonce:
                tx_hash, tx = safe_tx.execute(
                    self.tx_sender_account.key,
                    tx_gas=tx_gas,
                    tx_gas_price=gas_price,
                    tx_nonce=tx_nonce,
                    eip1559_speed=TxSpeed.NORMAL,
                )
                logger.error(
                    "Nonce problem, sending transaction for Safe %s with a new nonce %d and tx-hash %s",
                    multisig_tx.safe_id,
                    tx_nonce,
                    tx_hash.hex(),
                    exc_info=True,
                )
        except ValueError:
            logger.error("Problem resending transaction", exc_info=True)
            return None

        multisig_tx.ethereum_tx = EthereumTx.objects.create_from_tx_dict(tx, tx_hash)
        multisig_tx.full_clean(validate_unique=False)
        multisig_tx.save(update_fields=["ethereum_tx"])
        return multisig_tx.ethereum_tx

    # TODO Refactor and test
    def create_or_update_ethereum_tx(self, tx_hash: str) -> Optional[EthereumTx]:
        try:
            ethereum_tx = EthereumTx.objects.get(tx_hash=tx_hash)
            if ethereum_tx.block is None:
                tx_receipt = self.ethereum_client.get_transaction_receipt(tx_hash)
                if tx_receipt:
                    ethereum_tx.block = self.get_or_create_ethereum_block(
                        tx_receipt.blockNumber
                    )
                    ethereum_tx.gas_used = tx_receipt["gasUsed"]
                    ethereum_tx.status = tx_receipt.get("status")
                    ethereum_tx.transaction_index = tx_receipt["transactionIndex"]
                    ethereum_tx.save(
                        update_fields=[
                            "block",
                            "gas_used",
                            "status",
                            "transaction_index",
                        ]
                    )
            return ethereum_tx
        except EthereumTx.DoesNotExist:
            tx = self.ethereum_client.get_transaction(tx_hash)
            tx_receipt = self.ethereum_client.get_transaction_receipt(tx_hash)
            if tx:
                if tx_receipt:
                    ethereum_block = self.get_or_create_ethereum_block(
                        tx_receipt.blockNumber
                    )
                    return EthereumTx.objects.create_from_tx_dict(
                        tx,
                        tx_hash,
                        tx_receipt=tx_receipt.gasUsed,
                        ethereum_block=ethereum_block,
                    )
                return EthereumTx.objects.create_from_tx_dict(tx, tx_hash)

    # TODO Refactor and test
    def get_or_create_ethereum_block(self, block_number: int):
        try:
            return EthereumBlock.objects.get(number=block_number)
        except EthereumBlock.DoesNotExist:
            block = self.ethereum_client.get_block(block_number)
            return EthereumBlock.objects.create_from_block(block)
