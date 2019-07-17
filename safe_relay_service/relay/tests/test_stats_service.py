from django.test import TestCase

from eth_account import Account

from ..services import StatsServiceProvider
from .factories import EthereumEventFactory, SafeContractFactory
from .relay_test_case import RelayTestCaseMixin


class TestStatsService(RelayTestCaseMixin, TestCase):
    def test_get_balances(self):
        stats_service = StatsServiceProvider()
        safe_address = Account.create().address
        self.assertEqual(stats_service.get_balances(safe_address),
                         [{'token_address': None, 'value': 0}])

        value = 7
        self.send_ether(safe_address, 7)
        self.assertEqual(stats_service.get_balances(safe_address),
                         [{'token_address': None, 'value': value}])

        tokens_value = 12
        erc20 = self.deploy_example_erc20(tokens_value, safe_address)
        self.assertEqual(stats_service.get_balances(safe_address),
                         [{'token_address': None, 'value': value}])

        EthereumEventFactory(token_address=erc20.address, to=safe_address)
        self.assertCountEqual(stats_service.get_balances(safe_address),
                              [{'token_address': None, 'value': value},
                               {'token_address': erc20.address, 'value': tokens_value}])

    def test_get_relay_history_stats(self):
        stats_service = StatsServiceProvider()
        self.assertIsNotNone(stats_service.get_relay_history_stats())

    def test_get_relay_stats(self):
        stats_service = StatsServiceProvider()
        self.assertIsNotNone(stats_service.get_relay_stats())
