from logging import getLogger
from typing import Dict

from gnosis.eth import EthereumClient, EthereumClientProvider

from safe_relay_service.gas_station.gas_station import (GasStation,
                                                        GasStationProvider)

from ..models import SafeContract, SafeMultisigTx, SafeCreation2

logger = getLogger(__name__)


class StatsServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = StatsService(EthereumClientProvider(), GasStationProvider())
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class StatsService:
    def __init__(self, ethereum_client: EthereumClient, gas_station: GasStation):
        self.ethereum_client = ethereum_client
        self.gas_station = gas_station

    def get_gas_price_stats(self) -> Dict[str, any]:
        pass

    def get_relay_stats(self) -> Dict[str, any]:
        return {
            'safes_created': {
                'deployed': SafeContract.objects.deployed().count(),
                'not_deployed': SafeContract.objects.count(),
                'average_deploy_time': SafeContract.objects.get_average_deploy_time(),
                'payment_tokens': SafeCreation2.objects.get_tokens_usage(),
                'funds_stored': 1,  # Ether and tokens
            },
            'relayed_txs': {
                'total': SafeMultisigTx.objects.count(),
                'average_execution_time': SafeMultisigTx.objects.get_average_execution_time(),
                'pending_txs': SafeMultisigTx.objects.pending().count(),
                'payment_tokens': SafeMultisigTx.objects.get_tokens_usage(),
                'volume': 1,  # Ether and tokens
            }
        }
