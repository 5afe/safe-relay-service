from logging import getLogger
from typing import Dict

from gnosis.eth import EthereumClient, EthereumClientProvider

from safe_relay_service.gas_station.gas_station import (GasStation,
                                                        GasStationProvider)

from ..models import SafeContract, SafeCreation2, SafeMultisigTx

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
        deployed = SafeContract.objects.deployed().count()
        return {
            'safes_created': {
                'deployed': deployed,
                'not_deployed': SafeContract.objects.count() - deployed,
                'average_deploy_time_seconds': SafeContract.objects.get_average_deploy_time(),
                'payment_tokens': SafeCreation2.objects.get_tokens_usage(),
                'funds_stored': {
                    'ether': SafeContract.objects.get_total_balance(),
                    'tokens': SafeContract.objects.get_total_token_balance(),
                }
            },
            'relayed_txs': {
                'total': SafeMultisigTx.objects.count(),
                'average_execution_time_seconds': SafeMultisigTx.objects.get_average_execution_time(),
                'pending_txs': SafeMultisigTx.objects.pending().count(),
                'payment_tokens': SafeMultisigTx.objects.get_tokens_usage(),
                'volume': {
                    'ether': SafeContract.objects.get_total_volume(),
                    'tokens': SafeContract.objects.get_total_token_volume(),
                }
            }
        }
