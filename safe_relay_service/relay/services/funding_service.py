from logging import getLogger

from django.conf import settings

from eth_account import Account
from redis import Redis
from web3 import Web3

from gnosis.eth import EthereumClient, EthereumClientProvider

from safe_relay_service.gas_station.gas_station import GasStation, GasStationProvider

from ..repositories.redis_repository import EthereumNonceLock, RedisRepository

logger = getLogger(__name__)


class FundingServiceException(Exception):
    pass


class EtherLimitExceeded(FundingServiceException):
    pass


class FundingServiceProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            cls.instance = FundingService(
                EthereumClientProvider(),
                GasStationProvider(),
                RedisRepository().redis,
                settings.SAFE_FUNDER_PRIVATE_KEY,
                settings.SAFE_FUNDER_MAX_ETH,
            )
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class FundingService:
    def __init__(
        self,
        ethereum_client: EthereumClient,
        gas_station: GasStation,
        redis: Redis,
        funder_private_key: str,
        max_eth_to_send: int,
    ):
        self.ethereum_client = ethereum_client
        self.gas_station = gas_station
        self.redis = redis
        self.funder_account = Account.from_key(funder_private_key)
        self.max_eth_to_send = max_eth_to_send

    def send_eth_to(
        self,
        to: str,
        value: int,
        gas: int = 22000,
        gas_price=None,
        retry: bool = False,
        block_identifier="pending",
    ):
        if not gas_price:
            gas_price = self.gas_station.get_gas_prices().standard

        if self.max_eth_to_send and value > Web3.toWei(self.max_eth_to_send, "ether"):
            raise EtherLimitExceeded(
                "%d is bigger than %f" % (value, self.max_eth_to_send)
            )

        with EthereumNonceLock(
            self.redis,
            self.ethereum_client,
            self.funder_account.address,
            lock_timeout=60 * 2,
        ) as tx_nonce:
            logger.info("Fund safe=%s with %d", to, value)
            return self.ethereum_client.send_eth_to(
                self.funder_account.key,
                to,
                gas_price,
                value,
                gas=gas,
                retry=retry,
                block_identifier=block_identifier,
                nonce=tx_nonce,
            )
