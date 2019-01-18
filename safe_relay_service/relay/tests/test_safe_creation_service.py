import logging

from django.conf import settings

from gnosis.eth.tests.utils import deploy_example_erc20
from gnosis.eth.utils import get_eth_address_with_key
from gnosis.safe.tests.test_safe_service import TestSafeService

from safe_relay_service.gas_station.gas_station import GasStationMock
from safe_relay_service.tokens.tests.factories import TokenFactory

from ..services.safe_creation_service import (InvalidPaymentToken,
                                              SafeCreationService,
                                              SafeCreationServiceProvider)

logger = logging.getLogger(__name__)


class TestSafeCreationService(TestSafeService):

    def test_relay_provider_singleton(self):
        relay_service1 = SafeCreationServiceProvider()
        relay_service2 = SafeCreationServiceProvider()
        self.assertEqual(relay_service1, relay_service2)

    def test_estimate_safe_creation(self):
        gas_station = GasStationMock()
        gas_price = gas_station.get_gas_prices().fast
        relay_service = SafeCreationService(self.safe_service, gas_station, settings.SAFE_FIXED_CREATION_COST)

        number_owners = 4
        payment_token = None
        safe_creation_estimate = relay_service.estimate_safe_creation(number_owners, payment_token)
        self.assertGreater(safe_creation_estimate.gas, 0)
        self.assertEqual(safe_creation_estimate.gas_price, gas_price)
        self.assertGreater(safe_creation_estimate.payment, 0)
        estimated_payment = safe_creation_estimate.payment

        number_owners = 8
        payment_token = None
        safe_creation_estimate = relay_service.estimate_safe_creation(number_owners, payment_token)
        self.assertGreater(safe_creation_estimate.gas, 0)
        self.assertEqual(safe_creation_estimate.gas_price, gas_price)
        self.assertGreater(safe_creation_estimate.payment, estimated_payment)

        payment_token = get_eth_address_with_key()[0]
        with self.assertRaisesMessage(InvalidPaymentToken, payment_token):
            relay_service.estimate_safe_creation(number_owners, payment_token)

        erc20 = deploy_example_erc20(self.w3, 1000, self.w3.eth.accounts[0])
        number_owners = 4
        payment_token = erc20.address
        payment_token_db = TokenFactory(address=payment_token, fixed_eth_conversion=0.1)
        safe_creation_estimate = relay_service.estimate_safe_creation(number_owners, payment_token)
        self.assertGreater(safe_creation_estimate.gas, 0)
        self.assertEqual(safe_creation_estimate.gas_price, gas_price)
        self.assertGreater(safe_creation_estimate.payment, estimated_payment)
