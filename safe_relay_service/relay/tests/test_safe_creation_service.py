import logging

from django.conf import settings
from django.test import TestCase

from eth_account import Account

from gnosis.eth.utils import get_eth_address_with_key
from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from safe_relay_service.gas_station.gas_station import GasStationMock
from safe_relay_service.tokens.tests.factories import TokenFactory

from ..services.safe_creation_service import (InvalidPaymentToken,
                                              SafeCreationService,
                                              SafeCreationServiceProvider)

logger = logging.getLogger(__name__)


class TestSafeCreationService(SafeTestCaseMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.prepare_tests()

    def test_creation_service_provider_singleton(self):
        self.assertEqual(SafeCreationServiceProvider(), SafeCreationServiceProvider())

    def test_estimate_safe_creation(self):
        gas_station = GasStationMock()
        gas_price = gas_station.get_gas_prices().fast
        safe_creation_service = SafeCreationService(self.safe_service, gas_station, settings.SAFE_FUNDER_PRIVATE_KEY,
                                                    settings.SAFE_FIXED_CREATION_COST)

        number_owners = 4
        payment_token = None
        safe_creation_estimate = safe_creation_service.estimate_safe_creation(number_owners, payment_token)
        self.assertGreater(safe_creation_estimate.gas, 0)
        self.assertEqual(safe_creation_estimate.gas_price, gas_price)
        self.assertGreater(safe_creation_estimate.payment, 0)
        estimated_payment = safe_creation_estimate.payment

        number_owners = 8
        payment_token = None
        safe_creation_estimate = safe_creation_service.estimate_safe_creation(number_owners, payment_token)
        self.assertGreater(safe_creation_estimate.gas, 0)
        self.assertEqual(safe_creation_estimate.gas_price, gas_price)
        self.assertGreater(safe_creation_estimate.payment, estimated_payment)

        payment_token = get_eth_address_with_key()[0]
        with self.assertRaisesMessage(InvalidPaymentToken, payment_token):
            safe_creation_service.estimate_safe_creation(number_owners, payment_token)

        number_tokens = 1000
        owner = Account.create()
        erc20 = self.deploy_example_erc20(number_tokens, owner.address)
        number_owners = 4
        payment_token = erc20.address
        payment_token_db = TokenFactory(address=payment_token, fixed_eth_conversion=0.1)
        safe_creation_estimate = safe_creation_service.estimate_safe_creation(number_owners, payment_token)
        self.assertGreater(safe_creation_estimate.gas, 0)
        self.assertEqual(safe_creation_estimate.gas_price, gas_price)
        self.assertGreater(safe_creation_estimate.payment, estimated_payment)
