import datetime
from logging import getLogger
from typing import Any, Dict, List, Union

from django.db.models import Count
from django.db.models.functions import TruncDate
from django.utils import timezone

import requests
from pytz import utc
from web3 import Web3

from gnosis.eth import EthereumClient, EthereumClientProvider

from safe_relay_service.gas_station.gas_station import GasStation, GasStationProvider

from ..models import EthereumEvent, SafeContract, SafeMultisigTx

logger = getLogger(__name__)


class StatsServiceProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
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

    def get_balances(self, safe_address: str) -> List[Dict[str, Union[str, int]]]:
        """
        :param safe_address:
        :return: `{'token_address': str, 'balance': int}`. For ether, `token_address` is `None`
        """
        assert Web3.isChecksumAddress(
            safe_address
        ), f"Not valid address {safe_address} for getting balances"

        balance_query = {
            "jsonrpc": "2.0",
            "method": "eth_getBalance",
            "params": [safe_address, "latest"],
            "id": 0,
        }
        queries = [balance_query]
        tokens_used = list(
            EthereumEvent.objects.erc20_tokens_used_by_address(safe_address)
        )
        for i, token_used in enumerate(tokens_used):
            queries.append(
                {
                    "jsonrpc": "2.0",
                    "method": "eth_call",
                    "params": [
                        {
                            "to": token_used,  # Balance of
                            "data": "0x70a08231"
                            + "{:0>64}".format(safe_address.replace("0x", "").lower()),
                        },
                        "latest",
                    ],
                    "id": i + 1,
                }
            )
        response = requests.post(self.ethereum_client.ethereum_node_url, json=queries)
        balances = []
        for token_address, data in zip([None] + tokens_used, response.json()):
            value = 0 if data["result"] == "0x" else int(data["result"], 16)
            if value or not token_address:  # If value 0, ignore unless ether
                balances.append({"token_address": token_address, "balance": value})
        return balances

    def get_relay_history_stats(
        self, from_date: datetime.datetime = None, to_date: datetime.datetime = None
    ) -> Dict[str, Any]:

        from_date = (
            from_date if from_date else datetime.datetime(2018, 11, 1, tzinfo=utc)
        )
        to_date = to_date if to_date else timezone.now()

        def add_time_filter(queryset):
            return queryset.filter(created__range=(from_date, to_date))

        return {
            "safes_created": {
                "deployed": add_time_filter(SafeContract.objects.deployed())
                .annotate(created_date=TruncDate("created"))
                .values("created_date")
                .annotate(number=Count("*"))
                .order_by("created_date"),
                # 'average_deploy_time_seconds': SafeContract.objects.get_average_deploy_time_grouped(from_date, to_date),
                # 'average_deploy_time_total_seconds':
                #    SafeContract.objects.get_average_deploy_time_total_grouped(from_date, to_date),
                "payment_tokens": SafeContract.objects.get_creation_tokens_usage_grouped(
                    from_date, to_date
                ),
            },
            "relayed_txs": {
                "total": add_time_filter(
                    SafeMultisigTx.objects.annotate(created_date=TruncDate("created"))
                    .values("created_date")
                    .annotate(number=Count("*"))
                    .order_by("created_date")
                ),
                "average_execution_time_seconds": SafeMultisigTx.objects.get_average_execution_time_grouped(
                    from_date, to_date
                ),
                "payment_tokens": add_time_filter(
                    SafeMultisigTx.objects.get_tokens_usage_grouped()
                ),
            },
        }

    def get_relay_stats(
        self, from_date: datetime.datetime = None, to_date: datetime.datetime = None
    ) -> Dict[str, Any]:

        from_date = (
            from_date if from_date else datetime.datetime(2018, 11, 1, tzinfo=utc)
        )
        to_date = to_date if to_date else timezone.now()

        def add_time_filter(queryset):
            return queryset.filter(created__range=(from_date, to_date))

        deployed = add_time_filter(SafeContract.objects.deployed()).count()
        return {
            "safes_created": {
                "deployed": deployed,
                "not_deployed": add_time_filter(SafeContract.objects.all()).count()
                - deployed,
                # 'average_deploy_time_seconds': SafeContract.objects.get_average_deploy_time(from_date, to_date),
                # 'average_deploy_time_total_seconds':
                #     SafeContract.objects.get_average_deploy_time_total(from_date, to_date),
                "payment_tokens": SafeContract.objects.get_creation_tokens_usage(
                    from_date, to_date
                ),
            },
            "relayed_txs": {
                "total": add_time_filter(SafeMultisigTx.objects.all()).count(),
                "average_execution_time_seconds": SafeMultisigTx.objects.get_average_execution_time(
                    from_date, to_date
                ),
                "pending_txs": add_time_filter(
                    SafeMultisigTx.objects.pending()
                ).count(),
                "payment_tokens": add_time_filter(
                    SafeMultisigTx.objects.get_tokens_usage()
                ),
            },
        }
