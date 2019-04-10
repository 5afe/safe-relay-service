import logging

from eth_account import Account

from gnosis.safe.tests.test_safe_service import TestSafeService

from ..services.funding_service import FundingServiceProvider

logger = logging.getLogger(__name__)


class TestFundingService(TestSafeService):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.funding_service = FundingServiceProvider()

    def test_send_eth_to(self):
        to = Account.create().address
        value = 1

        tx_hash = self.funding_service.send_eth_to(to, value)
        tx_receipt = self.ethereum_client.get_transaction_receipt(tx_hash, timeout=200)
        self.assertEqual(tx_receipt.status, 1)
        self.assertEqual(self.ethereum_client.get_balance(to), value)
