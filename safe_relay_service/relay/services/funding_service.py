from logging import getLogger

from django.conf import settings

from gnosis.eth import EthereumService, EthereumServiceProvider

from safe_relay_service.gas_station.gas_station import (GasStation,
                                                        GasStationProvider)

logger = getLogger(__name__)


#TODO Test this service
class FundingServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = FundingService(EthereumServiceProvider(), GasStationProvider(),
                                          settings.SAFE_FUNDER_PRIVATE_KEY, settings.SAFE_FUNDER_MAX_ETH)
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class FundingService:
    def __init__(self, ethereum_service: EthereumService, gas_station: GasStation,
                 funder_private_key: str, max_eth_to_send: int):
        self.ethereum_service = ethereum_service
        self.gas_station = gas_station
        self.funder_private_key = funder_private_key
        self.max_eth_to_send = max_eth_to_send

    def send_eth_to(self, to: str, value: int, gas: int = 22000, gas_price=None,
                    retry: bool = False, block_identifier='pending'):
        if not gas_price:
            gas_price = self.gas_station.get_gas_prices().standard
        return self.ethereum_service.send_eth_to(self.funder_private_key, to, gas_price, value,
                                                 gas=gas,
                                                 retry=retry,
                                                 block_identifier=block_identifier,
                                                 max_eth_to_send=self.max_eth_to_send)
