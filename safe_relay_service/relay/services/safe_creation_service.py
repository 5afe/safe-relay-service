from logging import getLogger
from typing import Iterable, List, NamedTuple, Optional

from django.conf import settings

from eth_account import Account
from hexbytes import HexBytes
from redis import Redis

from gnosis.eth import EthereumClient, EthereumClientProvider
from gnosis.eth.constants import NULL_ADDRESS
from gnosis.safe import ProxyFactory, Safe
from gnosis.safe.safe import SafeCreationEstimate

from safe_relay_service.gas_station.gas_station import (GasStation,
                                                        GasStationProvider)
from safe_relay_service.tokens.models import Token
from safe_relay_service.tokens.price_oracles import CannotGetTokenPriceFromApi

from ..models import (EthereumTx, SafeContract, SafeCreation, SafeCreation2,
                      SafeTxStatus)
from ..repositories.redis_repository import EthereumNonceLock, RedisRepository

logger = getLogger(__name__)


class SafeCreationServiceException(Exception):
    pass


class InvalidPaymentToken(SafeCreationServiceException):
    pass


class SafeNotDeployed(SafeCreationServiceException):
    pass


class NotEnoughFundingForCreation(SafeCreationServiceException):
    pass


class SafeAlreadyExistsException(SafeCreationServiceException):
    pass


class SafeInfo(NamedTuple):
    address: str
    nonce: int
    threshold: int
    owners: List[str]
    master_copy: str
    version: str


class SafeCreationServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = SafeCreationService(GasStationProvider(),
                                               EthereumClientProvider(),
                                               RedisRepository().redis,
                                               settings.SAFE_CONTRACT_ADDRESS,
                                               settings.SAFE_OLD_CONTRACT_ADDRESS,
                                               settings.SAFE_PROXY_FACTORY_ADDRESS,
                                               settings.SAFE_FUNDER_PRIVATE_KEY,
                                               settings.SAFE_FIXED_CREATION_COST)
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class SafeCreationService:
    def __init__(self, gas_station: GasStation, ethereum_client: EthereumClient, redis: Redis,
                 safe_contract_address: str, safe_old_contract_address: str, proxy_factory_address: str,
                 safe_funder_private_key: str, safe_fixed_creation_cost: int):
        self.gas_station = gas_station
        self.ethereum_client = ethereum_client
        self.redis = redis
        self.safe_contract_address = safe_contract_address
        self.safe_old_contract_address = safe_old_contract_address
        self.proxy_factory = ProxyFactory(proxy_factory_address, self.ethereum_client)
        self.funder_account = Account.privateKeyToAccount(safe_funder_private_key)
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
        except Token.DoesNotExist:
            # Add the token for development purposes.
            token = Token.objects.create(address=address, name="Cash", symbol="cash", decimals=2, fixed_eth_conversion=1, gas=True)

        return token.get_eth_value()

    def _get_configured_gas_price(self) -> int:
        """
        :return: Gas price for txs
        """
        return self.gas_station.get_gas_prices().fast

    def create_safe_tx(self, s: int, owners: List[str], threshold: int,
                       payment_token: Optional[str]) -> SafeCreation:
        """
        Prepare creation tx for a new safe using classic CREATE method. Deprecated, it's recommended
        to use `create2_safe_tx`
        :param s: Random s value for ecdsa signature
        :param owners: Owners of the new Safe
        :param threshold: Minimum number of users required to operate the Safe
        :param payment_token: Address of the payment token, if ether is not used
        :rtype: SafeCreation
        :raises: InvalidPaymentToken
        """

        payment_token = payment_token or NULL_ADDRESS
        payment_token_eth_value = self._get_token_eth_value_or_raise(payment_token)
        gas_price: int = self._get_configured_gas_price()
        current_block_number = self.ethereum_client.current_block_number

        logger.debug('Building safe creation tx with gas price %d' % gas_price)
        safe_creation_tx = Safe.build_safe_creation_tx(self.ethereum_client, self.safe_old_contract_address,
                                                       s, owners, threshold, gas_price, payment_token,
                                                       self.funder_account.address,
                                                       payment_token_eth_value=payment_token_eth_value,
                                                       fixed_creation_cost=self.safe_fixed_creation_cost)

        safe_contract = SafeContract.objects.create(
            address=safe_creation_tx.safe_address,
            master_copy=safe_creation_tx.master_copy
        )

        # Enable tx and erc20 tracing
        SafeTxStatus.objects.create(safe=safe_contract,
                                    initial_block_number=current_block_number,
                                    tx_block_number=current_block_number,
                                    erc_20_block_number=current_block_number)

        return SafeCreation.objects.create(
            deployer=safe_creation_tx.deployer_address,
            safe=safe_contract,
            master_copy=safe_creation_tx.master_copy,
            funder=safe_creation_tx.funder,
            owners=owners,
            threshold=threshold,
            payment=safe_creation_tx.payment,
            tx_hash=safe_creation_tx.tx_hash.hex(),
            gas=safe_creation_tx.gas,
            gas_price=safe_creation_tx.gas_price,
            payment_token=None if safe_creation_tx.payment_token == NULL_ADDRESS else safe_creation_tx.payment_token,
            value=safe_creation_tx.tx_pyethereum.value,
            v=safe_creation_tx.v,
            r=safe_creation_tx.r,
            s=safe_creation_tx.s,
            data=safe_creation_tx.tx_pyethereum.data,
            signed_tx=safe_creation_tx.tx_raw
        )

    def create2_safe_tx(self, salt_nonce: int, owners: Iterable[str], threshold: int,
                        payment_token: Optional[str], setup_data: Optional[str], to: Optional[str]) -> SafeCreation2:
        """
        Prepare creation tx for a new safe using CREATE2 method
        :param salt_nonce: Random value for solidity `create2` salt
        :param owners: Owners of the new Safe
        :param threshold: Minimum number of users required to operate the Safe
        :param payment_token: Address of the payment token, otherwise `ether` is used
        :param setup_data: Data used for safe creation delegate call.
        :rtype: SafeCreation2
        :raises: InvalidPaymentToken
        """

        payment_token = payment_token or NULL_ADDRESS
        payment_token_eth_value = self._get_token_eth_value_or_raise(payment_token)
        gas_price: int = self._get_configured_gas_price()
        current_block_number = self.ethereum_client.current_block_number
        logger.debug('Building safe create2 tx with gas price %d', gas_price)
        safe_creation_tx = Safe.build_safe_create2_tx(self.ethereum_client, self.safe_contract_address,
                                                      self.proxy_factory.address, salt_nonce, owners, threshold,
                                                      gas_price, payment_token,
                                                      payment_token_eth_value=payment_token_eth_value,
                                                      fixed_creation_cost=self.safe_fixed_creation_cost,
                                                      setup_data=HexBytes(setup_data),
                                                      to=to,
                                                      )

        safe_contract, created = SafeContract.objects.get_or_create(
            address=safe_creation_tx.safe_address,
            defaults={
                'master_copy': safe_creation_tx.master_copy_address
            })

        if not created:
            raise SafeAlreadyExistsException(f'Safe={safe_contract.address} cannot be created, already exists')

        # Enable tx and erc20 tracing
        SafeTxStatus.objects.create(safe=safe_contract,
                                    initial_block_number=current_block_number,
                                    tx_block_number=current_block_number,
                                    erc_20_block_number=current_block_number)

        return SafeCreation2.objects.create(
            safe=safe_contract,
            master_copy=safe_creation_tx.master_copy_address,
            proxy_factory=safe_creation_tx.proxy_factory_address,
            salt_nonce=salt_nonce,
            owners=owners,
            threshold=threshold,
            to=to,  # Contract address for optional delegate call
            # data # Data payload for optional delegate call
            payment_token=None if safe_creation_tx.payment_token == NULL_ADDRESS else safe_creation_tx.payment_token,
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
        safe_creation2 = SafeCreation2.objects.get(safe=safe_address)

        if safe_creation2.tx_hash:
            logger.info('Safe=%s has already been deployed with tx-hash=%s', safe_address, safe_creation2.tx_hash)
            return safe_creation2

        if safe_creation2.payment_token and safe_creation2.payment_token != NULL_ADDRESS:
            safe_balance = self.ethereum_client.erc20.get_balance(safe_address, safe_creation2.payment_token)
        else:
            safe_balance = self.ethereum_client.get_balance(safe_address)

        if safe_balance < safe_creation2.payment:
            message = 'Balance=%d for safe=%s with payment-token=%s. Not found ' \
                      'required=%d' % (safe_balance,
                                       safe_address,
                                       safe_creation2.payment_token,
                                       safe_creation2.payment)
            logger.info(message)
            raise NotEnoughFundingForCreation(message)

        logger.info('Found %d balance for safe=%s with payment-token=%s. Required=%d', safe_balance,
                    safe_address, safe_creation2.payment_token, safe_creation2.payment)

        setup_data = HexBytes(safe_creation2.setup_data.tobytes())

        with EthereumNonceLock(self.redis, self.ethereum_client, self.funder_account.address,
                               timeout=60 * 2) as tx_nonce:
            ethereum_tx_sent = self.proxy_factory.deploy_proxy_contract_with_nonce(self.funder_account,
                                                                                   self.safe_contract_address,
                                                                                   setup_data,
                                                                                   safe_creation2.salt_nonce,
                                                                                   safe_creation2.gas_estimated,
                                                                                   safe_creation2.gas_price_estimated,
                                                                                   nonce=tx_nonce)
            EthereumTx.objects.create_from_tx(ethereum_tx_sent.tx, ethereum_tx_sent.tx_hash)
            safe_creation2.tx_hash = ethereum_tx_sent.tx_hash
            safe_creation2.save()
            logger.info('Deployed safe=%s with tx-hash=%s', safe_address, ethereum_tx_sent.tx_hash.hex())
            return safe_creation2

    def estimate_safe_creation(self, number_owners: int, payment_token: Optional[str] = None) -> SafeCreationEstimate:
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
        return Safe.estimate_safe_creation(self.ethereum_client,
                                           self.safe_old_contract_address, number_owners, gas_price, payment_token,
                                           payment_token_eth_value=payment_token_eth_value,
                                           fixed_creation_cost=fixed_creation_cost)

    def estimate_safe_creation2(self, number_owners: int, payment_token: Optional[str] = None) -> SafeCreationEstimate:
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
        return Safe.estimate_safe_creation_2(self.ethereum_client,
                                             self.safe_contract_address, self.proxy_factory.address,
                                             number_owners, gas_price, payment_token,
                                             payment_token_eth_value=payment_token_eth_value,
                                             fixed_creation_cost=fixed_creation_cost)

    def estimate_safe_creation_for_all_tokens(self, number_owners: int) -> List[SafeCreationEstimate]:
        # Estimate for eth, then calculate for the rest of the tokens
        ether_creation_estimate = self.estimate_safe_creation2(number_owners, NULL_ADDRESS)
        safe_creation_estimates = [ether_creation_estimate]
        token_gas_difference = 50000  # 50K gas more expensive than ether
        for token in Token.objects.gas_tokens():
            try:
                safe_creation_estimates.append(
                    SafeCreationEstimate(
                        gas=ether_creation_estimate.gas + token_gas_difference,
                        gas_price=ether_creation_estimate.gas_price,
                        payment=token.calculate_payment(ether_creation_estimate.payment),
                        payment_token=token.address,
                    )
                )
            except CannotGetTokenPriceFromApi:
                logger.error('Cannot get price for token=%s', token.address)
        return safe_creation_estimates

    def retrieve_safe_info(self, address: str) -> SafeInfo:
        safe = Safe(address, self.ethereum_client)
        if not self.ethereum_client.is_contract(address):
            raise SafeNotDeployed('Safe with address=%s not deployed' % address)
        nonce = safe.retrieve_nonce()
        threshold = safe.retrieve_threshold()
        owners = safe.retrieve_owners()
        master_copy = safe.retrieve_master_copy_address()
        version = safe.retrieve_version()
        return SafeInfo(address, nonce, threshold, owners, master_copy, version)
