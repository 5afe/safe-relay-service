import logging

from django.conf import settings
from django.urls import reverse

from eth_account import Account
from ethereum.utils import check_checksum
from faker import Faker
from rest_framework import status
from rest_framework.test import APITestCase

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.safe import Safe
from gnosis.safe.tests.utils import generate_salt_nonce

from safe_relay_service.tokens.tests.factories import TokenFactory

from ..models import SafeContract, SafeCreation2
from ..services.safe_creation_service import SafeCreationServiceProvider
from .relay_test_case import RelayTestCaseMixin

faker = Faker()

logger = logging.getLogger(__name__)


class TestViewsV3(RelayTestCaseMixin, APITestCase):
    def test_safe_creation_estimate(self):
        url = reverse('v3:safe-creation-estimates')
        number_owners = 4
        data = {
            'numberOwners': number_owners
        }

        response = self.client.post(url, data=data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        safe_creation_estimates = response.json()
        self.assertEqual(len(safe_creation_estimates), 1)
        safe_creation_estimate = safe_creation_estimates[0]
        self.assertEqual(safe_creation_estimate['paymentToken'], NULL_ADDRESS)

        token = TokenFactory(gas=True, fixed_eth_conversion=None)
        response = self.client.post(url, data=data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        safe_creation_estimates = response.json()
        # No price oracles, so no estimation
        self.assertEqual(len(safe_creation_estimates), 1)

        fixed_price_token = TokenFactory(gas=True, fixed_eth_conversion=1.0)
        response = self.client.post(url, data=data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        safe_creation_estimates = response.json()
        # Fixed price oracle, so estimation will work
        self.assertEqual(len(safe_creation_estimates), 2)
        safe_creation_estimate = safe_creation_estimates[1]
        self.assertEqual(safe_creation_estimate['paymentToken'], fixed_price_token.address)
        self.assertGreater(int(safe_creation_estimate['payment']), 0)
        self.assertGreater(int(safe_creation_estimate['gasPrice']), 0)
        self.assertGreater(int(safe_creation_estimate['gas']), 0)

    def test_safe_creation(self):
        salt_nonce = generate_salt_nonce()
        owners = [Account.create().address for _ in range(2)]
        data = {
            'saltNonce': salt_nonce,
            'owners': owners,
            'threshold': len(owners)
        }
        response = self.client.post(reverse('v3:safe-creation'), data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_json = response.json()
        safe_address = response_json['safe']
        self.assertTrue(check_checksum(safe_address))
        self.assertTrue(check_checksum(response_json['paymentReceiver']))
        self.assertEqual(response_json['paymentToken'], NULL_ADDRESS)
        self.assertEqual(int(response_json['payment']),
                         int(response_json['gasEstimated']) * int(response_json['gasPriceEstimated']))
        self.assertGreater(int(response_json['gasEstimated']), 0)
        self.assertGreater(int(response_json['gasPriceEstimated']), 0)
        self.assertGreater(len(response_json['setupData']), 2)
        self.assertEqual(response_json['masterCopy'], settings.SAFE_CONTRACT_ADDRESS)

        self.assertTrue(SafeContract.objects.filter(address=safe_address))
        self.assertTrue(SafeCreation2.objects.filter(owners__contains=[owners[0]]))
        safe_creation = SafeCreation2.objects.get(safe=safe_address)
        self.assertEqual(safe_creation.payment_token, None)
        # Payment includes deployment gas + gas to send eth to the deployer
        self.assertEqual(safe_creation.payment, safe_creation.wei_estimated_deploy_cost())

        # Deploy the Safe to check it
        self.send_ether(safe_address, int(response_json['payment']))
        safe_creation2 = SafeCreationServiceProvider().deploy_create2_safe_tx(safe_address)
        self.ethereum_client.get_transaction_receipt(safe_creation2.tx_hash, timeout=20)
        safe = Safe(safe_address, self.ethereum_client)
        self.assertEqual(safe.retrieve_master_copy_address(), response_json['masterCopy'])
        self.assertEqual(safe.retrieve_owners(), owners)

        # Test exception when same Safe is created
        response = self.client.post(reverse('v3:safe-creation'), data, format='json')
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn('SafeAlreadyExistsException', response.json()['exception'])

        data = {
            'salt_nonce': -1,
            'owners': owners,
            'threshold': 2
        }
        response = self.client.post(reverse('v3:safe-creation'), data, format='json')
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

    def test_safe_creation_with_fixed_cost(self):
        salt_nonce = generate_salt_nonce()
        owners = [Account.create().address for _ in range(2)]
        data = {
            'saltNonce': salt_nonce,
            'owners': owners,
            'threshold': len(owners)
        }

        fixed_creation_cost = 456
        with self.settings(SAFE_FIXED_CREATION_COST=fixed_creation_cost):
            SafeCreationServiceProvider.del_singleton()
            response = self.client.post(reverse('v3:safe-creation'), data, format='json')
            SafeCreationServiceProvider.del_singleton()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_json = response.json()
        safe_address = response_json['safe']
        self.assertTrue(check_checksum(safe_address))
        self.assertTrue(check_checksum(response_json['paymentReceiver']))
        self.assertEqual(response_json['paymentToken'], NULL_ADDRESS)
        self.assertEqual(response_json['payment'], str(fixed_creation_cost))
        self.assertGreater(int(response_json['gasEstimated']), 0)
        self.assertGreater(int(response_json['gasPriceEstimated']), 0)
        self.assertGreater(len(response_json['setupData']), 2)

    def test_safe_creation_with_payment_token(self):
        salt_nonce = generate_salt_nonce()
        owners = [Account.create().address for _ in range(2)]
        payment_token = Account.create().address
        data = {
            'saltNonce': salt_nonce,
            'owners': owners,
            'threshold': len(owners),
            'paymentToken': payment_token,
        }

        response = self.client.post(reverse('v3:safe-creation'), data=data, format='json')
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        response_json = response.json()
        self.assertIn('InvalidPaymentToken', response_json['exception'])
        self.assertIn(payment_token, response_json['exception'])

        fixed_eth_conversion = 0.1
        token_model = TokenFactory(address=payment_token, fixed_eth_conversion=fixed_eth_conversion)
        response = self.client.post(reverse('v3:safe-creation'), data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_json = response.json()
        safe_address = response_json['safe']
        self.assertTrue(check_checksum(safe_address))
        self.assertTrue(check_checksum(response_json['paymentReceiver']))
        self.assertEqual(response_json['paymentToken'], payment_token)
        self.assertEqual(int(response_json['payment']),
                         int(response_json['gasEstimated']) * int(response_json['gasPriceEstimated'])
                         * (1 / fixed_eth_conversion))
        self.assertGreater(int(response_json['gasEstimated']), 0)
        self.assertGreater(int(response_json['gasPriceEstimated']), 0)
        self.assertGreater(len(response_json['setupData']), 2)

        self.assertTrue(SafeContract.objects.filter(address=safe_address))
        self.assertTrue(SafeCreation2.objects.filter(owners__contains=[owners[0]]))
        safe_creation = SafeCreation2.objects.get(safe=safe_address)
        self.assertEqual(safe_creation.payment_token, payment_token)
        # Payment includes deployment gas + gas to send eth to the deployer
        self.assertEqual(safe_creation.payment, safe_creation.wei_estimated_deploy_cost() * (1 / fixed_eth_conversion))
