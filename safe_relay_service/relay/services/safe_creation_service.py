from logging import getLogger
from typing import Iterable, List, NamedTuple, Union

from django.conf import settings

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.safe.safe_service import (SafeCreationEstimate, SafeService,
                                      SafeServiceProvider)

from safe_relay_service.gas_station.gas_station import (GasStation,
                                                        GasStationProvider)
from safe_relay_service.tokens.models import Token

from ..models import SafeContract, SafeCreation

logger = getLogger(__name__)


class SafeCreationServiceException(Exception):
    pass


class InvalidPaymentToken(SafeCreationServiceException):
    pass


class SafeInfo(NamedTuple):
    address: str
    nonce: int
    threshold: int
    owners: List[str]
    master_copy: str
    version: str


class SafeCreationServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = SafeCreationService(SafeServiceProvider(), GasStationProvider(),
                                               settings.SAFE_FIXED_CREATION_COST)
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class SafeCreationService:
    def __init__(self, safe_service: SafeService, gas_station: GasStation, safe_fixed_creation_cost: int):
        self.safe_service = safe_service
        self.gas_station = gas_station
        self.safe_fixed_creation_cost = safe_fixed_creation_cost

    def _get_token_eth_value_or_raise(self, address: str) -> float:
        """
        :param address: Token address
        :return: Current eth value of the token
        :raises: InvalidPaymentToken
        """
        address = address or NULL_ADDRESS
        if address == NULL_ADDRESS:
            return 1.0

        try:
            token = Token.objects.get(address=address, gas=True)
            return token.get_eth_value()
        except Token.DoesNotExist:
            logger.warning('Cannot get value of token in eth: Gas token %s not valid' % address)
            raise InvalidPaymentToken(address)

    def create_safe_tx(self, s: int, owners: Iterable[str], threshold: int,
                       payment_token: Union[str, None]) -> SafeCreation:
        """
        Create models for safe tx
        :param s: Random s value for ecdsa signature
        :param owners: Owners of the new Safe
        :param threshold: Minimum number of users required to operate the Safe
        :param payment_token: Address of the payment token, if ether is not used
        :rtype: SafeCreation
        :raises: InvalidPaymentToken
        """

        payment_token = payment_token or NULL_ADDRESS
        payment_token_eth_value = self._get_token_eth_value_or_raise(payment_token)
        fast_gas_price: int = self.gas_station.get_gas_prices().fast
        logger.debug('Building safe creation tx with gas price %d' % fast_gas_price)
        safe_creation_tx = self.safe_service.build_safe_creation_tx(s, owners, threshold, fast_gas_price, payment_token,
                                                                    payment_token_eth_value=payment_token_eth_value,
                                                                    fixed_creation_cost=self.safe_fixed_creation_cost)

        safe_contract = SafeContract.objects.create(address=safe_creation_tx.safe_address,
                                                    master_copy=safe_creation_tx.master_copy)

        return SafeCreation.objects.create(
            deployer=safe_creation_tx.deployer_address,
            safe=safe_contract,
            master_copy=safe_creation_tx.master_copy,
            funder=safe_creation_tx.funder,
            owners=owners,
            threshold=threshold,
            payment=safe_creation_tx.payment,
            tx_hash=safe_creation_tx.tx_hash.hex(),
            gas=safe_creation_tx.gas,
            gas_price=safe_creation_tx.gas_price,
            payment_token=None if safe_creation_tx.payment_token == NULL_ADDRESS else safe_creation_tx.payment_token,
            value=safe_creation_tx.tx_pyethereum.value,
            v=safe_creation_tx.v,
            r=safe_creation_tx.r,
            s=safe_creation_tx.s,
            data=safe_creation_tx.tx_pyethereum.data,
            signed_tx=safe_creation_tx.tx_raw
        )

    def estimate_safe_creation(self, number_owners: int, payment_token: Union[str, None]) -> SafeCreationEstimate:
        """
        :param number_owners:
        :param payment_token:
        :return:
        :raises: InvalidPaymentToken
        """
        payment_token = payment_token or NULL_ADDRESS
        payment_token_eth_value = self._get_token_eth_value_or_raise(payment_token)
        gas_price = self.gas_station.get_gas_prices().fast
        fixed_creation_cost = self.safe_fixed_creation_cost
        return self.safe_service.estimate_safe_creation(number_owners, gas_price, payment_token,
                                                        payment_token_eth_value=payment_token_eth_value,
                                                        fixed_creation_cost=fixed_creation_cost)

    def retrieve_safe_info(self, address: str) -> SafeInfo:
        nonce = self.safe_service.retrieve_nonce(address)
        threshold = self.safe_service.retrieve_threshold(address)
        owners = self.safe_service.retrieve_owners(address)
        master_copy = self.safe_service.retrieve_master_copy_address(address)
        version = self.safe_service.retrieve_version(address)
        return SafeInfo(address, nonce, threshold, owners, master_copy, version)
