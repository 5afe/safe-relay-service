from logging import getLogger
from typing import Dict

from django.db.models import Avg, Count, DurationField, F, FloatField
from django.db.models.functions import Cast

from gnosis.eth import EthereumClient, EthereumClientProvider

from safe_relay_service.gas_station.gas_station import (GasStation,
                                                        GasStationProvider)

from ..models import SafeContract, SafeMultisigTx

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
        total_multisig_txs = SafeMultisigTx.objects.count()
        return {
            'safes_created': SafeContract.objects.deployed().count(),
            'relayed_txs': {
                'total': total_multisig_txs,
                'pending_txs': SafeMultisigTx.objects.exclude(ethereum_tx__block=None).count(),
                'payment_tokens': SafeMultisigTx.objects.values('gas_token').annotate(
                    number=Count('pk'), percentage=Cast(Count('pk') / float(total_multisig_txs) * 100.0, FloatField())),
                'average_execution_time':
                    SafeMultisigTx.objects.all().select_related(
                        'ethereum_tx', 'ethereum_tx__block'
                    ).annotate(
                        interval=Cast(F('ethereum_tx__block__timestamp') - F('created'), output_field=DurationField())
                    ).aggregate(median=Avg('interval'))['median'],
            }
        }
