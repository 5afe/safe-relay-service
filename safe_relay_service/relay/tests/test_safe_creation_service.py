import logging

from django.core.exceptions import ObjectDoesNotExist
from django.test import TestCase

from eth_account import Account

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.utils import get_eth_address_with_key

from safe_relay_service.tokens.tests.factories import TokenFactory

from ..services.safe_creation_service import (InvalidPaymentToken,
                                              NotEnoughFundingForCreation,
                                              SafeCreationServiceProvider,
                                              SafeNotDeployed)
from .relay_test_case import RelayTestCaseMixin

logger = logging.getLogger(__name__)


class TestSafeCreationService(RelayTestCaseMixin, TestCase):
    def test_deploy_create2_safe_tx(self):
        random_safe_address = Account.create().address
        with self.assertRaises(ObjectDoesNotExist):
            self.safe_creation_service.deploy_create2_safe_tx(random_safe_address)

        owner_accounts = [Account.create() for _ in range(4)]
        owners = [owner_account.address for owner_account in owner_accounts]

        salt_nonce = 17051863
        threshold = 2
        payment_token = None
        safe_creation_2 = self.safe_creation_service.create2_safe_tx(salt_nonce, owners, threshold, payment_token)
        safe_address = safe_creation_2.safe_id
        self.assertFalse(self.ethereum_client.is_contract(safe_address))
        self.assertIsNone(safe_creation_2.tx_hash)
        with self.assertRaisesMessage(NotEnoughFundingForCreation, str(safe_creation_2.payment)):
            self.safe_creation_service.deploy_create2_safe_tx(safe_address)
        self.send_ether(safe_address, safe_creation_2.payment)
        new_safe_creation_2 = self.safe_creation_service.deploy_create2_safe_tx(safe_address)
        self.assertTrue(new_safe_creation_2.tx_hash)
        self.assertTrue(self.ethereum_client.is_contract(safe_address))

        # If already deployed it will return `SafeCreation2`
        another_safe_creation2 = self.safe_creation_service.deploy_create2_safe_tx(safe_address)
        self.assertEqual(another_safe_creation2, new_safe_creation_2)

    def test_creation_service_provider_singleton(self):
        self.assertEqual(SafeCreationServiceProvider(), SafeCreationServiceProvider())

    def test_estimate_safe_creation(self):
        gas_price = self.safe_creation_service._get_configured_gas_price()

        number_owners = 4
        payment_token = None
        safe_creation_estimate = self.safe_creation_service.estimate_safe_creation(number_owners, payment_token)
        self.assertGreater(safe_creation_estimate.gas, 0)
        self.assertEqual(safe_creation_estimate.gas_price, gas_price)
        self.assertGreater(safe_creation_estimate.payment, 0)
        self.assertEqual(safe_creation_estimate.payment_token, NULL_ADDRESS)
        estimated_payment = safe_creation_estimate.payment

        number_owners = 8
        payment_token = None
        safe_creation_estimate = self.safe_creation_service.estimate_safe_creation(number_owners, payment_token)
        self.assertGreater(safe_creation_estimate.gas, 0)
        self.assertEqual(safe_creation_estimate.gas_price, gas_price)
        self.assertGreater(safe_creation_estimate.payment, estimated_payment)
        self.assertEqual(safe_creation_estimate.payment_token, NULL_ADDRESS)

        payment_token = get_eth_address_with_key()[0]
        with self.assertRaisesMessage(InvalidPaymentToken, payment_token):
            self.safe_creation_service.estimate_safe_creation(number_owners, payment_token)

        number_tokens = 1000
        owner = Account.create()
        erc20 = self.deploy_example_erc20(number_tokens, owner.address)
        number_owners = 4
        payment_token = erc20.address
        payment_token_db = TokenFactory(address=payment_token, fixed_eth_conversion=0.1)
        safe_creation_estimate = self.safe_creation_service.estimate_safe_creation(number_owners, payment_token)
        self.assertGreater(safe_creation_estimate.gas, 0)
        self.assertEqual(safe_creation_estimate.gas_price, gas_price)
        self.assertGreater(safe_creation_estimate.payment, estimated_payment)
        self.assertEqual(safe_creation_estimate.payment_token, payment_token)

    def test_estimate_safe_creation2(self):
        gas_price = self.safe_creation_service._get_configured_gas_price()

        number_owners = 4
        payment_token = None
        safe_creation_estimate = self.safe_creation_service.estimate_safe_creation2(number_owners, payment_token)
        self.assertGreater(safe_creation_estimate.gas, 0)
        self.assertEqual(safe_creation_estimate.gas_price, gas_price)
        self.assertGreater(safe_creation_estimate.payment, 0)
        self.assertEqual(safe_creation_estimate.payment_token, NULL_ADDRESS)
        estimated_payment = safe_creation_estimate.payment

        number_owners = 8
        payment_token = None
        safe_creation_estimate = self.safe_creation_service.estimate_safe_creation2(number_owners, payment_token)
        self.assertGreater(safe_creation_estimate.gas, 0)
        self.assertEqual(safe_creation_estimate.gas_price, gas_price)
        self.assertGreater(safe_creation_estimate.payment, estimated_payment)
        self.assertEqual(safe_creation_estimate.payment_token, NULL_ADDRESS)

        payment_token = get_eth_address_with_key()[0]
        with self.assertRaisesMessage(InvalidPaymentToken, payment_token):
            self.safe_creation_service.estimate_safe_creation2(number_owners, payment_token)

        number_tokens = 1000
        owner = Account.create()
        erc20 = self.deploy_example_erc20(number_tokens, owner.address)
        number_owners = 4
        payment_token = erc20.address
        payment_token_db = TokenFactory(address=payment_token, fixed_eth_conversion=0.1)
        safe_creation_estimate = self.safe_creation_service.estimate_safe_creation2(number_owners, payment_token)
        self.assertGreater(safe_creation_estimate.gas, 0)
        self.assertEqual(safe_creation_estimate.gas_price, gas_price)
        self.assertGreater(safe_creation_estimate.payment, estimated_payment)
        self.assertEqual(safe_creation_estimate.payment_token, payment_token)

    def test_estimate_safe_creation_for_all_tokens(self):
        number_owners = 4
        safe_creation_estimates = self.safe_creation_service.estimate_safe_creation_for_all_tokens(number_owners)
        self.assertEqual(len(safe_creation_estimates), 1)
        safe_creation_estimate = safe_creation_estimates[0]
        self.assertEqual(safe_creation_estimate.payment_token, NULL_ADDRESS)

        token = TokenFactory(gas=True, fixed_eth_conversion=None)
        safe_creation_estimates = self.safe_creation_service.estimate_safe_creation_for_all_tokens(number_owners)
        # No price oracles, so no estimation
        self.assertEqual(len(safe_creation_estimates), 1)

        fixed_price_token = TokenFactory(gas=True, fixed_eth_conversion=1.0)
        safe_creation_estimates = self.safe_creation_service.estimate_safe_creation_for_all_tokens(number_owners)
        # Fixed price oracle, so estimation will work
        self.assertEqual(len(safe_creation_estimates), 2)
        safe_creation_estimate = safe_creation_estimates[1]
        self.assertEqual(safe_creation_estimate.payment_token, fixed_price_token.address)
        self.assertGreater(safe_creation_estimate.payment, 0)
        self.assertGreater(safe_creation_estimate.gas_price, 0)
        self.assertGreater(safe_creation_estimate.gas, 0)

    def test_retrieve_safe_info(self):
        fake_safe_address = Account.create().address
        with self.assertRaisesMessage(SafeNotDeployed, fake_safe_address):
            self.safe_creation_service.retrieve_safe_info(fake_safe_address)

        threshold = 1
        safe_address = self.deploy_test_safe(threshold=threshold).safe_address
        safe_info = self.safe_creation_service.retrieve_safe_info(safe_address)
        self.assertEqual(safe_info.threshold, threshold)
