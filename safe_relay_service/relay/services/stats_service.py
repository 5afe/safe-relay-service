import datetime
from logging import getLogger
from typing import Dict

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

from pytz import utc

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

    def get_relay_history_stats(self, from_date: datetime.datetime = None,
                                to_date: datetime.datetime = None) -> Dict[str, any]:

        from_date = from_date if from_date else datetime.datetime(2018, 1, 1, tzinfo=utc)
        to_date = to_date if to_date else timezone.now()

        def add_time_filter(queryset):
            return queryset.filter(created__range=(from_date, to_date))

        return {
            'safes_created': {
                'deployed': add_time_filter(SafeContract.objects.deployed()).annotate(
                    created_date=TruncDate('created')).values('created_date').annotate(number=Count('*')
                                                                                       ).order_by('created_date'),
                'average_deploy_time_seconds': SafeContract.objects.get_average_deploy_time_grouped(from_date, to_date),
                'payment_tokens': SafeContract.objects.get_creation_tokens_usage_grouped(from_date, to_date),
                'funds_stored': {
                    'ether': SafeContract.objects.get_total_balance_grouped(from_date, to_date),
                    'tokens': SafeContract.objects.get_total_token_balance_grouped(from_date, to_date),
                }
            },
            'relayed_txs': {
                'total': add_time_filter(SafeMultisigTx.objects.annotate(
                    created_date=TruncDate('created')).values('created_date').annotate(number=Count('*')
                                                                                       ).order_by('created_date')),
                'average_execution_time_seconds': SafeMultisigTx.objects.get_average_execution_time_grouped(from_date,
                                                                                                            to_date),
                'payment_tokens': add_time_filter(SafeMultisigTx.objects.get_tokens_usage_grouped()),
                'volume': {
                    'ether': SafeContract.objects.get_total_volume_grouped(from_date, to_date),
                    'tokens': SafeContract.objects.get_total_token_volume_grouped(from_date, to_date),
                }
            }
        }

    def get_relay_stats(self, from_date: datetime.datetime = None,
                        to_date: datetime.datetime = None) -> Dict[str, any]:

        from_date = from_date if from_date else datetime.datetime(2018, 1, 1, tzinfo=utc)
        to_date = to_date if to_date else timezone.now()

        def add_time_filter(queryset):
            return queryset.filter(created__range=(from_date, to_date))

        deployed = add_time_filter(SafeContract.objects.deployed()).count()
        return {
            'safes_created': {
                'deployed': deployed,
                'not_deployed': add_time_filter(SafeContract.objects.all()).count() - deployed,
                'average_deploy_time_seconds': SafeContract.objects.get_average_deploy_time(from_date, to_date),
                'payment_tokens': SafeContract.objects.get_creation_tokens_usage(from_date, to_date),
                'funds_stored': {
                    'ether': SafeContract.objects.get_total_balance(from_date, to_date),  #FIXME
                    'tokens': SafeContract.objects.get_total_token_balance(from_date, to_date),  #FIXME
                }
            },
            'relayed_txs': {
                'total': add_time_filter(SafeMultisigTx.objects.all()).count(),
                'average_execution_time_seconds': SafeMultisigTx.objects.get_average_execution_time(from_date, to_date),
                'pending_txs': add_time_filter(SafeMultisigTx.objects.pending()).count(),
                'payment_tokens': add_time_filter(SafeMultisigTx.objects.get_tokens_usage()),
                'volume': {
                    'ether': SafeContract.objects.get_total_volume(from_date, to_date),
                    'tokens': SafeContract.objects.get_total_token_volume(from_date, to_date),
                }
            }
        }
