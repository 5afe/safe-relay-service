from django.conf import settings

from gnosis.eth import EthereumClientProvider
from gnosis.eth.constants import NULL_ADDRESS
from ethereum.utils import (check_checksum)

class Circles:
    magic_signup_gas = 3376826000000000
    ethereum_client = EthereumClientProvider()

    def estimate_signup_gas(self):
        return self.magic_signup_gas

    def pack_address(self, address):
    	assert check_checksum(address)
    	return "000000000000000000000000" + address[2:]

    def is_circles_token(self, address):
    	call_args = {
    	    'to': settings.CIRCLES_HUB_ADDRESS,
            'value': 0,
            'gas': 0,
            'gasPrice': 0,
            'data': '0xa18b506b' + self.pack_address(address)
    	}
    	return self.ethereum_client.w3.eth.call(call_args)
