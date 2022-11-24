from django.conf import settings
from hexbytes import HexBytes

from web3 import Web3

from gnosis.eth import EthereumClient
from gnosis.eth.constants import NULL_ADDRESS

MAPPING_NULL_PREFIX: str = "0" * 24


class CirclesService:
    def __init__(self, ethereum_client: EthereumClient, gas_price: int = 1):
        """
        :param ethereum_client:
        :param gas_price: Gas price when paid in Circles token
        """
        self.ethereum_client = ethereum_client
        self.gas_price = gas_price

    def get_gas_price(self) -> int:
        """
        Returns the gas price for transactions with Circles token
        :return: Gas price
        """
        return self.gas_price

    def pack_address(self, token_address: str) -> str:
        """
        Prepares Circles token address
        :param token_address:
        :return: packed string
        """
        assert Web3.isChecksumAddress(token_address)
        return MAPPING_NULL_PREFIX + token_address[2:]

    def is_circles_token(self, token_address: str) -> bool:
        """
        Checks if given Token is known by Circles Hub
        :param token_address:
        :return: true if Circles Token otherwise false
        """
        call_args = {
            "to": settings.CIRCLES_HUB_ADDRESS,
            # Calling tokenToUser mapping of Hub contract;
            "data": "0xa18b506b" + self.pack_address(token_address),
        }
        call_result = self.ethereum_client.w3.eth.call(call_args)
        return HexBytes(call_result).hex() != NULL_ADDRESS

    def is_token_deployed(self, safe_address: str) -> bool:
        """
        Checks if Safe address has a deployed Token connected to it
        :param safe_address:
        :return: true if Circles Token exists otherwise false
        """
        call_args = {
            "to": settings.CIRCLES_HUB_ADDRESS,
            # Calling userToToken mapping of Hub contract;
            "data": "0x28d249fe" + self.pack_address(safe_address),
        }
        call_result = self.ethereum_client.w3.eth.call(call_args)
        return HexBytes(call_result).hex() != NULL_ADDRESS + MAPPING_NULL_PREFIX

    def is_organization_deployed(self, safe_address: str) -> bool:
        """
        Checks if Safe address has a deployed Organization connected to it
        :param safe_address:
        :return: true if Circles Organization exists otherwise false
        """
        call_args = {
            "to": settings.CIRCLES_HUB_ADDRESS,
            # Calling organization mapping of Hub contract;
            "data": "0x5a1f7406" + self.pack_address(safe_address),
        }
        call_result = self.ethereum_client.w3.eth.call(call_args)
        return HexBytes(call_result).hex() != NULL_ADDRESS + MAPPING_NULL_PREFIX
