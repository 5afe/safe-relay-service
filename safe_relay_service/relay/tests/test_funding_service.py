from django.test import TestCase

from eth_account import Account

from ..services.funding_service import EtherLimitExceeded, FundingServiceProvider
from .relay_test_case import RelayTestCaseMixin


class TestFundingService(RelayTestCaseMixin, TestCase):
    def test_send_eth_to(self):
        to = Account.create().address
        value = 1

        tx_hash = self.funding_service.send_eth_to(to, value)
        tx_receipt = self.ethereum_client.get_transaction_receipt(tx_hash, timeout=200)
        self.assertEqual(tx_receipt.status, 1)
        self.assertEqual(self.ethereum_client.get_balance(to), value)

        with self.assertRaises(EtherLimitExceeded):
            self.funding_service.max_eth_to_send = 1
            self.funding_service.send_eth_to(to, self.w3.toWei(1.1, "ether"))

        FundingServiceProvider.del_singleton()
