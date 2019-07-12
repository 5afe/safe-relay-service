from django.test import TestCase

from ..services import StatsServiceProvider
from .relay_test_case import RelayTestCaseMixin


class TestStatsService(RelayTestCaseMixin, TestCase):
    def test_get_relay_history_stats(self):
        stats_service = StatsServiceProvider()
        self.assertIsNotNone(stats_service.get_relay_history_stats())

    def test_get_relay_stats(self):
        stats_service = StatsServiceProvider()
        self.assertIsNotNone(stats_service.get_relay_stats())
