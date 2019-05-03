import logging

from django.test import TestCase
from eth_account import Account
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from ..services.funding_service import FundingServiceProvider

logger = logging.getLogger(__name__)


class TestFundingService(TestCase, SafeTestCaseMixin):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.prepare_tests()
        cls.funding_service = FundingServiceProvider()

    def test_send_eth_to(self):
        to = Account.create().address
        value = 1

        tx_hash = self.funding_service.send_eth_to(to, value)
        tx_receipt = self.ethereum_client.get_transaction_receipt(tx_hash, timeout=200)
        self.assertEqual(tx_receipt.status, 1)
        self.assertEqual(self.ethereum_client.get_balance(to), value)
