import logging

from django.conf import settings
from django.test import TestCase

from gnosis.eth import EthereumServiceProvider
from hexbytes import HexBytes

logger = logging.getLogger(__name__)

LOG_TITLE_WIDTH = 100

GAS_PRICE = settings.SAFE_GAS_PRICE


class TestHelpers(TestCase):

    def setUp(self):
        self.ethereum_service = EthereumServiceProvider()
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

    def test_estimate_data_gas(self):
        self.assertEqual(self.ethereum_service.estimate_data_gas(HexBytes('')), 0)
        self.assertEqual(self.ethereum_service.estimate_data_gas(HexBytes('0x00')), 4)
        self.assertEqual(self.ethereum_service.estimate_data_gas(HexBytes('0x000204')), 4 + 68 * 2)
        self.assertEqual(self.ethereum_service.estimate_data_gas(HexBytes('0x050204')), 68 * 3)
        self.assertEqual(self.ethereum_service.estimate_data_gas(HexBytes('0x0502040000')), 68 * 3 + 4 * 2)
        self.assertEqual(self.ethereum_service.estimate_data_gas(HexBytes('0x050204000001')), 68 * 4 + 4 * 2)
        self.assertEqual(self.ethereum_service.estimate_data_gas(HexBytes('0x00050204000001')), 4 + 68 * 4 + 4 * 2)

    def test_provider_singleton(self):
        ethereum_service1 = EthereumServiceProvider()
        ethereum_service2 = EthereumServiceProvider()
        self.assertEqual(ethereum_service1, ethereum_service2)

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

    def test_wait_for_tx_receipt(self):
        value = 1
        to = self.w3.eth.accounts[-1]

        tx_hash = self.ethereum_service.send_eth_to(to=to, gas_price=GAS_PRICE, value=value)
        receipt1 = self.ethereum_service.get_transaction_receipt(tx_hash, timeout=None)
        receipt2 = self.ethereum_service.get_transaction_receipt(tx_hash, timeout=20)
        self.assertIsNotNone(receipt1)
        self.assertEqual(receipt1, receipt2)

        fake_tx_hash = self.w3.sha3(0)
        self.assertIsNone(self.ethereum_service.get_transaction_receipt(fake_tx_hash, timeout=None))
        self.assertIsNone(self.ethereum_service.get_transaction_receipt(fake_tx_hash, timeout=1))
