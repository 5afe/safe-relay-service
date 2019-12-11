from django.conf import settings
from logging import getLogger

from gnosis.eth import EthereumClientProvider
from gnosis.eth.constants import NULL_ADDRESS
from ethereum.utils import (check_checksum)

logger = getLogger(__name__)

class Circles:
    magic_signup_gas = 3999092000000000
    gas_price = 1
    ethereum_client = EthereumClientProvider()

    def estimate_signup_gas(self):
        return self.magic_signup_gas

    def estimate_gas_price(self):
        return self.gas_price

    def pack_address(self, address):
        assert check_checksum(address)
        return "000000000000000000000000" + address[2:]

    def is_circles_token(self, address):
        call_args = {
            'to': settings.CIRCLES_HUB_ADDRESS,
            'data': '0xa18b506b' + self.pack_address(address)
        }
        return self.ethereum_client.w3.eth.call(call_args)
