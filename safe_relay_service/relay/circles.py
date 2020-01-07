from django.conf import settings
from logging import getLogger

from gnosis.eth import EthereumClientProvider
from ethereum.utils import (check_checksum)
from safe_relay_service.relay.services import TransactionServiceProvider

logger = getLogger(__name__)


class Circles:

    value = 0
    data = "0x519c6377000000000000000000000000000000000000000000000"
      + "0000000000000000020000000000000000000000000000000000000000"
      + "0000000000000000000000007436972636c65730000000000000000000"
      + "0000000000000000000000000000000"
    operation = 0
    gas_token = NULL_ADDRESS

    magic_signup_gas = 3999092000000000

    gas_price = 1 #gas price when paid in circles token
    ethereum_client = EthereumClientProvider()

    def estimate_signup_gas(self, address):
        '''estimates gas costs of circles token deployment using standard signup data string'''
        transaction_estimation = TransactionServiceProvider().estimate_tx(
            address,
            settings.CIRCLES_HUB_ADDRESS,
            value,
            data,
            operation,
            gas_token)
        return transaction_estimation

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
