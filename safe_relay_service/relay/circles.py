from django.conf import settings
from logging import getLogger

from gnosis.eth import EthereumClientProvider
from web3 import Web3


class Circles:
    def __init__(self):
        self.gas_price = 1  # gas price when paid in circles token
        self.ethereum_client = EthereumClientProvider()

    def estimate_gas_price(self):
        return self.gas_price

    def pack_address(self, address):
        assert Web3.isChecksumAddress(address)
        return "000000000000000000000000" + address[2:]

    def is_circles_token(self, address):
        call_args = {
            "to": settings.CIRCLES_HUB_ADDRESS,
            "data": "0xa18b506b" + self.pack_address(address),
        }
        return self.ethereum_client.w3.eth.call(call_args)
