from django.conf import settings
from logging import getLogger

from gnosis.eth.constants import NULL_ADDRESS
from .transaction_service import TransactionServiceProvider

logger = getLogger(__name__)

class CirclesService:

    def __init__(self):
        self.value = 0
        self.data = ("0x519c6377000000000000000000000000000000000000000000000"
            "0000000000000000020000000000000000000000000000000000000000"
            "0000000000000000000000007436972636c65730000000000000000000"
            "0000000000000000000000000000000")
        self.operation = 0
        self.gas_token = NULL_ADDRESS

    def estimate_signup_gas(self, address):
        '''estimates gas costs of circles token deployment using standard signup data string'''
        logger.info('address %s data %s', address, self.data)
        transaction_estimation = TransactionServiceProvider().estimate_tx(
            address,
            settings.CIRCLES_HUB_ADDRESS,
            self.value,
            self.data,
            self.operation,
            self.gas_token)
        return (transaction_estimation.safe_tx_gas + transaction_estimation.base_gas) * transaction_estimation.gas_price