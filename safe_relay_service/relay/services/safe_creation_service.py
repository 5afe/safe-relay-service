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

from ..models import EthereumTx, SafeContract, SafeCreation2, SafeTxStatus
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
    fallback_handler: str


class SafeCreationServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = SafeCreationService(GasStationProvider(),
                                               EthereumClientProvider(),
                                               RedisRepository().redis,
                                               settings.SAFE_CONTRACT_ADDRESS,
                                               settings.SAFE_PROXY_FACTORY_ADDRESS,
                                               settings.SAFE_DEFAULT_CALLBACK_HANDLER,
                                               settings.SAFE_FUNDER_PRIVATE_KEY,
                                               settings.SAFE_FIXED_CREATION_COST)
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class SafeCreationV1_0_0ServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = SafeCreationService(GasStationProvider(),
                                               EthereumClientProvider(),
                                               RedisRepository().redis,
                                               settings.SAFE_V1_0_0_CONTRACT_ADDRESS,
                                               settings.SAFE_PROXY_FACTORY_V1_0_0_ADDRESS,
                                               settings.SAFE_DEFAULT_CALLBACK_HANDLER,
                                               settings.SAFE_FUNDER_PRIVATE_KEY,
                                               settings.SAFE_FIXED_CREATION_COST,
                                               settings.SAFE_AUTO_FUND,
                                               settings.SAFE_AUTO_APPROVE_TOKEN)
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class SafeCreationService:
    def __init__(self, gas_station: GasStation, ethereum_client: EthereumClient, redis: Redis,
                 safe_contract_address: str, proxy_factory_address: str, default_callback_handler: str,
                 safe_funder_private_key: str, safe_fixed_creation_cost: int, safe_auto_fund: bool,
                 safe_auto_approve_token: bool):
        self.gas_station = gas_station
        self.ethereum_client = ethereum_client
        self.redis = redis
        self.safe_contract_address = safe_contract_address
        self.proxy_factory = ProxyFactory(proxy_factory_address, self.ethereum_client)
        self.default_callback_handler = default_callback_handler
        self.funder_account = Account.from_key(safe_funder_private_key)
        self.safe_fixed_creation_cost = safe_fixed_creation_cost
        self.safe_auto_fund = safe_auto_fund
        self.safe_auto_approve_token = safe_auto_approve_token

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
            if self.safe_auto_approve_token:
                # Add the token for development purposes.
                token = Token.objects.create(address=address, name="Cash", symbol="cash", decimals=2, fixed_eth_conversion=0.006, gas=True)
            else:
                logger.warning('Cannot get value of token in eth: Gas token %s not valid', address)
                raise InvalidPaymentToken(address)

        return token.get_eth_value()

    def _get_configured_gas_price(self) -> int:
        """
        :return: Gas price for txs
        """
        return self.gas_station.get_gas_prices().fast

    def create2_safe_tx(self, salt_nonce: int, owners: Iterable[str], threshold: int,
                        payment_token: Optional[str], setup_data: Optional[str], to: Optional[str],
                        callback: Optional[str]) -> SafeCreation2:
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
        callback = callback or NULL_ADDRESS
        payment_token = payment_token or NULL_ADDRESS
        payment_token_eth_value = self._get_token_eth_value_or_raise(payment_token)
        gas_price: int = self._get_configured_gas_price()
        current_block_number = self.ethereum_client.current_block_number
        logger.debug('Building safe create2 tx with gas price %d', gas_price)
        safe_creation_tx = Safe.build_safe_create2_tx(self.ethereum_client, self.safe_contract_address,
                                                      self.proxy_factory.address, salt_nonce, owners, threshold,
                                                      gas_price, payment_token,
                                                      fallback_handler=self.default_callback_handler,
                                                      payment_token_eth_value=payment_token_eth_value,
                                                      fixed_creation_cost=self.safe_fixed_creation_cost,
                                                      setup_data=HexBytes(setup_data if setup_data else '0x'),
                                                      to=to,
                                                      callback=callback
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
            callback=callback,
        )

    def deploy_create2_safe_tx(self, safe_address: str) -> SafeCreation2:
        """
        Deploys safe if SafeCreation2 exists.
        :param safe_address:
        :return: tx_hash
        """


        safe_creation2: SafeCreation2 = SafeCreation2.objects.get(safe=safe_address)

        if safe_creation2.tx_hash:
            logger.info('Safe=%s has already been deployed with tx-hash=%s', safe_address, safe_creation2.tx_hash)
            return safe_creation2


        if safe_creation2.payment_token and safe_creation2.payment_token != NULL_ADDRESS:
            safe_balance = self.ethereum_client.erc20.get_balance(safe_address, safe_creation2.payment_token)
        else:
            safe_balance = self.ethereum_client.get_balance(safe_address)

        if safe_balance < safe_creation2.payment:
            message = 'Balance=%d for safe=%s with payment-token=%s. Not found ' \
                      'required=%d\n' % (safe_balance,
                                       safe_address,
                                       safe_creation2.payment_token,
                                       safe_creation2.payment)


            # Be sure we are actually using an erc20.
            if self.safe_auto_fund and safe_creation2.payment_token and safe_creation2.payment_token != NULL_ADDRESS:
                # Send funds from deployers address to the contract.
                # NOTE: THIS IS FOR DEVELOPMENT PURPOSES ONLY (self.safe_auto_fund should be False on production)
                amount_to_send = 1000000000000000000000
                funder_balance = self.ethereum_client.erc20.get_balance(self.funder_account.address, safe_creation2.payment_token)


                if amount_to_send < funder_balance:
                    message = message + 'Sending %d from account %s to %s.' % (
                        amount_to_send,
                        self.funder_account.address,
                        safe_address,
                    )

                    self.ethereum_client.erc20.send_tokens(safe_address,
                        amount_to_send,
                        safe_creation2.payment_token,
                        self.funder_account.privateKey)

                else:
                    message = message + 'Cannot seed wallet with funds. Please faucet %s' % (self.funder_account.address)

                logger.info(message)
                raise NotEnoughFundingForCreation(message)

        logger.info('Found %d balance for safe=%s with payment-token=%s. Required=%d', safe_balance,
                    safe_address, safe_creation2.payment_token, safe_creation2.payment)

        setup_data = HexBytes(safe_creation2.setup_data.tobytes())

        logger.info(setup_data)

        with EthereumNonceLock(self.redis, self.ethereum_client, self.funder_account.address,
                               timeout=60 * 2) as tx_nonce:
            logger.info('Calling deploy_proxy_contract_with_callback with: funder=%s address=%s setup_data=%s salt_nonce=%s callback=%s',
                self.funder_account,
                self.safe_contract_address,
                setup_data,
                safe_creation2.salt_nonce,
                safe_creation2.callback)
            proxy_factory = ProxyFactory(safe_creation2.proxy_factory, self.ethereum_client)
            ethereum_tx_sent = proxy_factory.deploy_proxy_contract_with_nonce(self.funder_account,
                                                                              safe_creation2.master_copy,
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
                                             fallback_handler=self.default_callback_handler,
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
        fallback_handler = safe.retrieve_fallback_handler()
        return SafeInfo(address, nonce, threshold, owners, master_copy, version, fallback_handler)
