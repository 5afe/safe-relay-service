import math
from logging import getLogger
from typing import Iterable, List, NoReturn, Optional

from django.conf import settings

from eth_account import Account
from hexbytes import HexBytes
from redis import Redis

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.safe import ProxyFactory, Safe
from gnosis.safe.exceptions import CannotRetrieveSafeInfoException
from gnosis.safe.safe import SafeCreationEstimate, SafeInfo

from safe_relay_service.gas_station.gas_station import GasStation, GasStationProvider
from safe_relay_service.tokens.models import Token
from safe_relay_service.tokens.price_oracles import CannotGetTokenPriceFromApi

from ..models import EthereumTx, SafeContract, SafeCreation2, SafeTxStatus
from ..repositories.redis_repository import EthereumNonceLock, RedisRepository

logger = getLogger(__name__)


class SafeCreationServiceException(Exception):
    pass


class InvalidPaymentToken(SafeCreationServiceException):
    pass


class SafeNotDeployed(SafeCreationServiceException):
    pass


class CannotRetrieveSafeInfo(SafeCreationServiceException):
    pass


class NotEnoughFundingForCreation(SafeCreationServiceException):
    pass


class SafeAlreadyExistsException(SafeCreationServiceException):
    pass


class DeployTransactionDoesNotExist(SafeCreationServiceException):
    pass


class SafeCreationServiceProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = SafeCreationService(
                GasStationProvider(),
                EthereumClientProvider(),
                RedisRepository().redis,
                settings.SAFE_CONTRACT_ADDRESS,
                settings.SAFE_PROXY_FACTORY_ADDRESS,
                settings.SAFE_DEFAULT_CALLBACK_HANDLER,
                settings.SAFE_FUNDER_PRIVATE_KEY,
                settings.SAFE_FIXED_CREATION_COST,
            )
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class SafeCreationV1_0_0ServiceProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = SafeCreationService(
                GasStationProvider(),
                EthereumClientProvider(),
                RedisRepository().redis,
                settings.SAFE_V1_0_0_CONTRACT_ADDRESS,
                settings.SAFE_PROXY_FACTORY_V1_0_0_ADDRESS,
                settings.SAFE_DEFAULT_CALLBACK_HANDLER,
                settings.SAFE_FUNDER_PRIVATE_KEY,
                settings.SAFE_FIXED_CREATION_COST,
            )
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class SafeCreationService:
    def __init__(
        self,
        gas_station: GasStation,
        ethereum_client: EthereumClient,
        redis: Redis,
        safe_contract_address: str,
        proxy_factory_address: str,
        default_callback_handler: str,
        safe_funder_private_key: str,
        safe_fixed_creation_cost: int,
    ):
        self.gas_station = gas_station
        self.ethereum_client = ethereum_client
        self.redis = redis
        self.safe_contract_address = safe_contract_address
        self.proxy_factory = ProxyFactory(proxy_factory_address, self.ethereum_client)
        self.default_callback_handler = default_callback_handler
        self.funder_account = Account.from_key(safe_funder_private_key)
        self.safe_fixed_creation_cost = safe_fixed_creation_cost

    def _get_token_eth_value_or_raise(self, address: str) -> float:
        """
        :param address: Token address
        :return: Current eth value of the token
        :raises: InvalidPaymentToken, CannotGetTokenPriceFromApi
        """
        address = address or NULL_ADDRESS
        if address == NULL_ADDRESS:
            return 1.0

        try:
            token = Token.objects.get(address=address, gas=True)
            return token.get_eth_value()
        except Token.DoesNotExist:
            logger.warning(
                "Cannot get value of token in eth: Gas token %s not valid", address
            )
            raise InvalidPaymentToken(address)

    def _get_configured_gas_price(self) -> int:
        """
        :return: Gas price for txs
        """
        return self.gas_station.get_gas_prices().fast

    def _check_safe_balance(self, safe_creation2: SafeCreation2) -> NoReturn:
        """
        Check there are enough funds to deploy a Safe. Raises `NotEnoughFundingForCreation`
        if not
        :param safe_creation2:
        :return:
        :raises: NotEnoughFundingForCreation
        """
        safe_address = safe_creation2.safe_id
        if (
            safe_creation2.payment_token
            and safe_creation2.payment_token != NULL_ADDRESS
        ):
            safe_balance = self.ethereum_client.erc20.get_balance(
                safe_address, safe_creation2.payment_token
            )
        else:
            safe_balance = self.ethereum_client.get_balance(safe_address)

        if safe_balance < safe_creation2.payment:
            message = (
                "Balance=%d for safe=%s with payment-token=%s. Not found "
                "required=%d"
                % (
                    safe_balance,
                    safe_address,
                    safe_creation2.payment_token,
                    safe_creation2.payment,
                )
            )
            logger.info(message)
            raise NotEnoughFundingForCreation(message)
        else:
            logger.info(
                "Found %d balance for safe=%s with payment-token=%s. Required=%d",
                safe_balance,
                safe_address,
                safe_creation2.payment_token,
                safe_creation2.payment,
            )

    def existing_predicted_address(self, salt_nonce: int, owners: Iterable[str]) -> str:
        """
        Return a previously predicted Safe address.
        Note that the prediction parameters are not updated for the SafeCreation2 object
        :param salt_nonce: Random value for solidity `create2` salt
        :param owners: Owners of the new Safe
        :rtype: str
        """
        try:
            # The salt_nonce is deterministicly generated from the owner address
            safe_creation = (
                SafeCreation2.objects.filter(
                    owners__contains=owners, salt_nonce=salt_nonce
                )
                .order_by("created")
                .first()
            )
            if not safe_creation:
                return NULL_ADDRESS
            logger.info(
                "The relayer had already predicted an address for this owner. Safe addr: %s, owner: %s",
                safe_creation.safe_id,
                owners,
            )
            return safe_creation.safe_id
        except SafeCreation2.DoesNotExist:
            return NULL_ADDRESS

    def predict_address(
        self,
        salt_nonce: int,
        owners: Iterable[str],
        threshold: int,
        payment_token: Optional[str],
    ) -> str:
        """
        Return the predicted Safe address
        :param salt_nonce: Random value for solidity `create2` salt
        :param owners: Owners of the new Safe
        :param threshold: Minimum number of users required to operate the Safe
        :param payment_token: Address of the payment token, otherwise `ether` is used
        :rtype: str
        :raises: InvalidPaymentToken
        """

        payment_token = payment_token or NULL_ADDRESS
        payment_token_eth_value = self._get_token_eth_value_or_raise(payment_token)
        gas_price: int = self._get_configured_gas_price()
        current_block_number = self.ethereum_client.current_block_number

        logger.info(
            "Safe.build_safe_create2_tx params: %s %s %s %s %s %s %s %s %s %s %s",
            self.safe_contract_address,
            self.proxy_factory.address,
            salt_nonce,
            owners,
            threshold,
            gas_price,
            payment_token,
            self.funder_account.address,
            self.default_callback_handler,
            payment_token_eth_value,
            self.safe_fixed_creation_cost,
        )

        safe_creation_tx = Safe.build_safe_create2_tx(
            self.ethereum_client,
            self.safe_contract_address,
            self.proxy_factory.address,
            salt_nonce,
            owners,
            threshold,
            gas_price,
            payment_token,
            payment_receiver=self.funder_account.address,
            fallback_handler=self.default_callback_handler,
            payment_token_eth_value=payment_token_eth_value,
            fixed_creation_cost=self.safe_fixed_creation_cost,
        )
        return safe_creation_tx.safe_address

    def create2_safe_tx(
        self,
        salt_nonce: int,
        owners: Iterable[str],
        threshold: int,
        payment_token: Optional[str],
    ) -> SafeCreation2:
        """
        Prepare creation tx for a new safe using CREATE2 method
        :param salt_nonce: Random value for solidity `create2` salt
        :param owners: Owners of the new Safe
        :param threshold: Minimum number of users required to operate the Safe
        :param payment_token: Address of the payment token, otherwise `ether` is used
        :rtype: SafeCreation2
        :raises: InvalidPaymentToken
        """

        payment_token = payment_token or NULL_ADDRESS
        payment_token_eth_value = self._get_token_eth_value_or_raise(payment_token)
        gas_price: int = self._get_configured_gas_price()
        current_block_number = self.ethereum_client.current_block_number
        safe_creation_tx = Safe.build_safe_create2_tx(
            self.ethereum_client,
            self.safe_contract_address,
            self.proxy_factory.address,
            salt_nonce,
            owners,
            threshold,
            gas_price,
            payment_token,
            payment_receiver=self.funder_account.address,
            fallback_handler=self.default_callback_handler,
            payment_token_eth_value=payment_token_eth_value,
            fixed_creation_cost=self.safe_fixed_creation_cost,
        )
        safe_contract, created = SafeContract.objects.get_or_create(
            address=safe_creation_tx.safe_address,
            defaults={"master_copy": safe_creation_tx.master_copy_address},
        )

        if not created:
            raise SafeAlreadyExistsException(
                f"Safe={safe_contract.address} cannot be created, already exists"
            )

        # Enable tx and erc20 tracing
        SafeTxStatus.objects.create(
            safe=safe_contract,
            initial_block_number=current_block_number,
            tx_block_number=current_block_number,
            erc_20_block_number=current_block_number,
        )

        return SafeCreation2.objects.create(
            safe=safe_contract,
            master_copy=safe_creation_tx.master_copy_address,
            proxy_factory=safe_creation_tx.proxy_factory_address,
            salt_nonce=salt_nonce,
            owners=owners,
            threshold=threshold,
            # to  # Contract address for optional delegate call
            # data # Data payload for optional delegate call
            payment_token=None
            if safe_creation_tx.payment_token == NULL_ADDRESS
            else safe_creation_tx.payment_token,
            payment=safe_creation_tx.payment,
            payment_receiver=safe_creation_tx.payment_receiver,
            setup_data=safe_creation_tx.safe_setup_data,
            gas_estimated=safe_creation_tx.gas,
            gas_price_estimated=safe_creation_tx.gas_price,
        )

    def deploy_create2_safe_tx(self, safe_address: str) -> SafeCreation2:
        """
        Deploys safe if SafeCreation2 exists.
        :param safe_address:
        :return: tx_hash
        """
        safe_creation2: SafeCreation2 = SafeCreation2.objects.get(safe=safe_address)
        logger.info(f"Safe Creation Info {safe_creation2}")

        if safe_creation2.tx_hash:
            logger.info(
                "Safe=%s has already been deployed with tx-hash=%s",
                safe_address,
                safe_creation2.tx_hash,
            )
            return safe_creation2

        self._check_safe_balance(safe_creation2)

        setup_data = HexBytes(safe_creation2.setup_data.tobytes())
        proxy_factory = ProxyFactory(safe_creation2.proxy_factory, self.ethereum_client)
        with EthereumNonceLock(
            self.redis,
            self.ethereum_client,
            self.funder_account.address,
            lock_timeout=60 * 2,
        ) as tx_nonce:
            ethereum_tx_sent = proxy_factory.deploy_proxy_contract_with_nonce(
                self.funder_account,
                safe_creation2.master_copy,
                setup_data,
                safe_creation2.salt_nonce,
                gas=safe_creation2.gas_estimated + 50000,  # Just in case
                gas_price=safe_creation2.gas_price_estimated+8,
                nonce=tx_nonce,
            )
            EthereumTx.objects.create_from_tx_dict(
                ethereum_tx_sent.tx, ethereum_tx_sent.tx_hash
            )
            safe_creation2.tx_hash = ethereum_tx_sent.tx_hash
            safe_creation2.save(update_fields=["tx_hash"])
            logger.info(
                "Send transaction to deploy Safe=%s with tx-hash=%s",
                safe_address,
                ethereum_tx_sent.tx_hash.hex(),
            )
            return safe_creation2

    def deploy_again_create2_safe_tx(self, safe_address: str) -> SafeCreation2:
        """
        Try to deploy Safe again with a higher gas price
        :param safe_address:
        :return: tx_hash
        """
        safe_creation2: SafeCreation2 = SafeCreation2.objects.get(safe=safe_address)

        if not safe_creation2.tx_hash:
            message = f"Safe={safe_address} deploy transaction does not exist"
            logger.info(message)
            raise DeployTransactionDoesNotExist(message)

        if safe_creation2.block_number is not None:
            message = (
                f"Safe={safe_address} has already been deployed with tx-hash={safe_creation2.tx_hash} "
                f"on block-number={safe_creation2.block_number}"
            )
            logger.info(message)
            raise SafeAlreadyExistsException(message)

        ethereum_tx: EthereumTx = EthereumTx.objects.get(tx_hash=safe_creation2.tx_hash)
        assert ethereum_tx, "Ethereum tx cannot be missing"

        self._check_safe_balance(safe_creation2)

        setup_data = HexBytes(safe_creation2.setup_data.tobytes())
        proxy_factory = ProxyFactory(safe_creation2.proxy_factory, self.ethereum_client)
        # Increase gas price a little
        gas_price = math.ceil(
            max(self.gas_station.get_gas_prices().fast, ethereum_tx.gas_price) * 1.1
        )
        ethereum_tx_sent = proxy_factory.deploy_proxy_contract_with_nonce(
            self.funder_account,
            safe_creation2.master_copy,
            setup_data,
            safe_creation2.salt_nonce,
            gas=safe_creation2.gas_estimated + 50000,  # Just in case
            gas_price=gas_price,
            nonce=ethereum_tx.nonce,
        )  # Replace old transaction
        EthereumTx.objects.create_from_tx_dict(
            ethereum_tx_sent.tx, ethereum_tx_sent.tx_hash
        )
        safe_creation2.tx_hash = ethereum_tx_sent.tx_hash.hex()
        safe_creation2.save(update_fields=["tx_hash"])
        logger.info(
            "Send again transaction to deploy Safe=%s with tx-hash=%s",
            safe_address,
            safe_creation2.tx_hash,
        )
        return safe_creation2

    def estimate_safe_creation2(
        self, number_owners: int, payment_token: Optional[str] = None
    ) -> SafeCreationEstimate:
        """
        :param number_owners:
        :param payment_token:
        :return:
        :raises: InvalidPaymentToken
        """
        payment_token = payment_token or NULL_ADDRESS
        payment_token_eth_value = self._get_token_eth_value_or_raise(payment_token)
        gas_price = self._get_configured_gas_price()
        fixed_creation_cost = self.safe_fixed_creation_cost
        return Safe.estimate_safe_creation_2(
            self.ethereum_client,
            self.safe_contract_address,
            self.proxy_factory.address,
            number_owners,
            gas_price,
            payment_token,
            payment_receiver=self.funder_account.address,
            fallback_handler=self.default_callback_handler,
            payment_token_eth_value=payment_token_eth_value,
            fixed_creation_cost=fixed_creation_cost,
        )

    def estimate_safe_creation_for_all_tokens(
        self, number_owners: int
    ) -> List[SafeCreationEstimate]:
        # Estimate for eth, then calculate for the rest of the tokens
        ether_creation_estimate = self.estimate_safe_creation2(
            number_owners, NULL_ADDRESS
        )
        safe_creation_estimates = [ether_creation_estimate]
        token_gas_difference = 50000  # 50K gas more expensive than ether
        for token in Token.objects.gas_tokens():
            try:
                safe_creation_estimates.append(
                    SafeCreationEstimate(
                        gas=ether_creation_estimate.gas + token_gas_difference,
                        gas_price=ether_creation_estimate.gas_price,
                        payment=token.calculate_payment(
                            ether_creation_estimate.payment
                        ),
                        payment_token=token.address,
                    )
                )
            except CannotGetTokenPriceFromApi:
                logger.error("Cannot get price for token=%s", token.address)
        return safe_creation_estimates

    def retrieve_safe_info(self, address: str) -> SafeInfo:
        safe = Safe(address, self.ethereum_client)
        if not self.ethereum_client.is_contract(address):
            raise SafeNotDeployed("Safe with address=%s not deployed" % address)

        try:
            return safe.retrieve_all_info()
        except CannotRetrieveSafeInfoException as e:
            raise CannotRetrieveSafeInfo(address) from e
