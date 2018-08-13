from django.test import TestCase

from ..gas_station import GasStation, NoBlocksFound


class TestGasStation(TestCase):
    def test_gas_station(self):
        gas_station = GasStation(http_provider_uri='http://localhost:8545',
                                 number_of_blocks=0)

        with self.assertRaises(NoBlocksFound):
            gas_station.calculate_gas_prices()

        number_of_blocks = 50
        gas_station = GasStation(http_provider_uri='http://localhost:8545',
                                 number_of_blocks=number_of_blocks)
        w3 = gas_station.w3
        account1 = w3.eth.accounts[-1]
        account2 = w3.eth.accounts[-2]

        if w3.eth.blockNumber < number_of_blocks:
            # Mine some blocks
            eth_balance = w3.toWei(0.00001, 'ether')
            for _ in range(number_of_blocks - w3.eth.blockNumber + 2):
                w3.eth.waitForTransactionReceipt(w3.eth.sendTransaction({
                    'from': account1,
                    'to': account2,
                    'value': eth_balance
                }))
                w3.eth.waitForTransactionReceipt(w3.eth.sendTransaction({
                    'from': account2,
                    'to': account1,
                    'value': eth_balance
                }))

        gas_prices = gas_station.calculate_gas_prices()
        self.assertIsNotNone(gas_prices)
        self.assertGreaterEqual(gas_prices.lowest, 1)
        self.assertGreaterEqual(gas_prices.safe_low, 1)
        self.assertGreaterEqual(gas_prices.standard, 1)
        self.assertGreaterEqual(gas_prices.fast, 1)
        self.assertGreaterEqual(gas_prices.fastest, 1)
