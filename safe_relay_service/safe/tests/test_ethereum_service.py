import logging

from django.conf import settings
from django.test import TestCase

from ..ethereum_service import EthereumService

logger = logging.getLogger(__name__)

LOG_TITLE_WIDTH = 100

GAS_PRICE = settings.SAFE_GAS_PRICE


class TestHelpers(TestCase):

    def setUp(self):
        self.ethereum_service = EthereumService()
        self.w3 = self.ethereum_service.w3

    def test_check_tx_with_confirmations(self):
        logger.info("Test Check Tx with confirmations".center(LOG_TITLE_WIDTH, '-'))
        value = 1
        to = self.w3.eth.accounts[-1]

        tx_hash = self.ethereum_service.send_eth_to(to=to, gas_price=GAS_PRICE, value=value)
        self.assertFalse(self.ethereum_service.check_tx_with_confirmations(tx_hash, 2))

        _ = self.ethereum_service.send_eth_to(to=to, gas_price=GAS_PRICE, value=value)
        self.assertFalse(self.ethereum_service.check_tx_with_confirmations(tx_hash, 2))

        _ = self.ethereum_service.send_eth_to(to=to, gas_price=GAS_PRICE, value=value)
        self.assertTrue(self.ethereum_service.check_tx_with_confirmations(tx_hash, 2))

    def test_send_eth(self):
        w3 = self.w3

        to = w3.eth.accounts[1]

        balance = w3.eth.getBalance(to)
        value = w3.toWei(settings.SAFE_FUNDER_MAX_ETH, 'ether') // 2

        self.ethereum_service.send_eth_to(to=to,
                                          gas_price=GAS_PRICE,
                                          value=value)

        new_balance = w3.eth.getBalance(to)

        self.assertTrue(new_balance == (balance + value))

    def test_send_eth_without_key(self):
        with self.settings(SAFE_FUNDER_PRIVATE_KEY=None):
            self.test_send_eth()
