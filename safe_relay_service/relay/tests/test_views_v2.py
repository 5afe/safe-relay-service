import logging

from django.conf import settings
from django.urls import reverse

from eth_account import Account
from faker import Faker
from rest_framework import status
from rest_framework.test import APITestCase
from web3 import Web3

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.utils import get_eth_address_with_invalid_checksum
from gnosis.safe import Safe
from gnosis.safe.tests.utils import generate_salt_nonce

from safe_relay_service.tokens.tests.factories import TokenFactory

from ..models import SafeContract, SafeCreation2
from ..services.safe_creation_service import SafeCreationV1_0_0ServiceProvider
from .factories import SafeContractFactory
from .relay_test_case import RelayTestCaseMixin

faker = Faker()

logger = logging.getLogger(__name__)


class TestViewsV2(RelayTestCaseMixin, APITestCase):
    def test_safe_creation_estimate(self):
        url = reverse("v2:safe-creation-estimates")
        number_owners = 4
        data = {"numberOwners": number_owners}

        response = self.client.post(url, data=data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        safe_creation_estimates = response.json()
        self.assertEqual(len(safe_creation_estimates), 1)
        safe_creation_estimate = safe_creation_estimates[0]
        self.assertEqual(safe_creation_estimate["paymentToken"], NULL_ADDRESS)

        token = TokenFactory(gas=True, fixed_eth_conversion=None)
        response = self.client.post(url, data=data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        safe_creation_estimates = response.json()
        # No price oracles, so no estimation
        self.assertEqual(len(safe_creation_estimates), 1)

        fixed_price_token = TokenFactory(gas=True, fixed_eth_conversion=1.0)
        response = self.client.post(url, data=data, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        safe_creation_estimates = response.json()
        # Fixed price oracle, so estimation will work
        self.assertEqual(len(safe_creation_estimates), 2)
        safe_creation_estimate = safe_creation_estimates[1]
        self.assertEqual(
            safe_creation_estimate["paymentToken"], fixed_price_token.address
        )
        self.assertGreater(int(safe_creation_estimate["payment"]), 0)
        self.assertGreater(int(safe_creation_estimate["gasPrice"]), 0)
        self.assertGreater(int(safe_creation_estimate["gas"]), 0)

    def test_safe_creation(self):
        salt_nonce = generate_salt_nonce()
        owners = [Account.create().address for _ in range(2)]
        data = {"saltNonce": salt_nonce, "owners": owners, "threshold": len(owners)}
        response = self.client.post(reverse("v2:safe-creation"), data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_json = response.json()
        safe_address = response_json["safe"]
        self.assertTrue(Web3.is_checksum_address(safe_address))
        self.assertTrue(Web3.is_checksum_address(response_json["paymentReceiver"]))
        self.assertEqual(response_json["paymentToken"], NULL_ADDRESS)
        self.assertEqual(
            int(response_json["payment"]),
            int(response_json["gasEstimated"])
            * int(response_json["gasPriceEstimated"]),
        )
        self.assertGreater(int(response_json["gasEstimated"]), 0)
        self.assertGreater(int(response_json["gasPriceEstimated"]), 0)
        self.assertGreater(len(response_json["setupData"]), 2)
        self.assertEqual(
            response_json["masterCopy"], settings.SAFE_V1_0_0_CONTRACT_ADDRESS
        )

        self.assertTrue(SafeContract.objects.filter(address=safe_address))
        self.assertTrue(SafeCreation2.objects.filter(owners__contains=[owners[0]]))
        safe_creation = SafeCreation2.objects.get(safe=safe_address)
        self.assertEqual(safe_creation.payment_token, None)
        # Payment includes deployment gas + gas to send eth to the deployer
        self.assertEqual(
            safe_creation.payment, safe_creation.wei_estimated_deploy_cost()
        )

        # Deploy the Safe to check it
        self.send_ether(safe_address, int(response_json["payment"]))
        safe_creation2 = SafeCreationV1_0_0ServiceProvider().deploy_create2_safe_tx(
            safe_address
        )
        self.ethereum_client.get_transaction_receipt(safe_creation2.tx_hash, timeout=20)
        safe = Safe(safe_address, self.ethereum_client)
        self.assertEqual(
            safe.retrieve_master_copy_address(), response_json["masterCopy"]
        )
        self.assertEqual(safe.retrieve_owners(), owners)

        # Test exception when same Safe is created
        response = self.client.post(reverse("v2:safe-creation"), data, format="json")
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn("SafeAlreadyExistsException", response.json()["exception"])

        data = {"salt_nonce": -1, "owners": owners, "threshold": 2}
        response = self.client.post(reverse("v2:safe-creation"), data, format="json")
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

    def test_safe_creation_with_fixed_cost(self):
        salt_nonce = generate_salt_nonce()
        owners = [Account.create().address for _ in range(2)]
        data = {"saltNonce": salt_nonce, "owners": owners, "threshold": len(owners)}

        fixed_creation_cost = 123
        with self.settings(SAFE_FIXED_CREATION_COST=fixed_creation_cost):
            SafeCreationV1_0_0ServiceProvider.del_singleton()
            response = self.client.post(
                reverse("v2:safe-creation"), data, format="json"
            )
            SafeCreationV1_0_0ServiceProvider.del_singleton()

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_json = response.json()
        safe_address = response_json["safe"]
        self.assertTrue(Web3.is_checksum_address(safe_address))
        self.assertTrue(Web3.is_checksum_address(response_json["paymentReceiver"]))
        self.assertEqual(response_json["paymentToken"], NULL_ADDRESS)
        self.assertEqual(response_json["payment"], str(fixed_creation_cost))
        self.assertGreater(int(response_json["gasEstimated"]), 0)
        self.assertGreater(int(response_json["gasPriceEstimated"]), 0)
        self.assertGreater(len(response_json["setupData"]), 2)

    def test_safe_creation_with_payment_token(self):
        salt_nonce = generate_salt_nonce()
        owners = [Account.create().address for _ in range(2)]
        payment_token = Account.create().address
        data = {
            "saltNonce": salt_nonce,
            "owners": owners,
            "threshold": len(owners),
            "paymentToken": payment_token,
        }

        response = self.client.post(
            reverse("v2:safe-creation"), data=data, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        response_json = response.json()
        self.assertIn("InvalidPaymentToken", response_json["exception"])
        self.assertIn(payment_token, response_json["exception"])

        fixed_eth_conversion = 0.1
        token_model = TokenFactory(
            address=payment_token, fixed_eth_conversion=fixed_eth_conversion
        )
        response = self.client.post(reverse("v2:safe-creation"), data, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response_json = response.json()
        safe_address = response_json["safe"]
        self.assertTrue(Web3.is_checksum_address(safe_address))
        self.assertTrue(Web3.is_checksum_address(response_json["paymentReceiver"]))
        self.assertEqual(response_json["paymentToken"], payment_token)
        self.assertEqual(
            int(response_json["payment"]),
            int(response_json["gasEstimated"])
            * int(response_json["gasPriceEstimated"])
            * (1 / fixed_eth_conversion),
        )
        self.assertGreater(int(response_json["gasEstimated"]), 0)
        self.assertGreater(int(response_json["gasPriceEstimated"]), 0)
        self.assertGreater(len(response_json["setupData"]), 2)

        self.assertTrue(SafeContract.objects.filter(address=safe_address))
        self.assertTrue(SafeCreation2.objects.filter(owners__contains=[owners[0]]))
        safe_creation = SafeCreation2.objects.get(safe=safe_address)
        self.assertEqual(safe_creation.payment_token, payment_token)
        # Payment includes deployment gas + gas to send eth to the deployer
        self.assertEqual(
            safe_creation.payment,
            safe_creation.wei_estimated_deploy_cost() * (1 / fixed_eth_conversion),
        )

    def test_safe_multisig_tx_estimate_v2(self):
        my_safe_address = get_eth_address_with_invalid_checksum()
        response = self.client.post(
            reverse("v2:safe-multisig-tx-estimate", args=(my_safe_address,)),
            data={},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        my_safe_address = Account.create().address
        response = self.client.post(
            reverse("v2:safe-multisig-tx-estimate", args=(my_safe_address,)),
            data={},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        initial_funding = self.w3.to_wei(0.0001, "ether")
        to = Account.create().address
        data = {"to": to, "value": initial_funding // 2, "data": "0x", "operation": 1}

        safe = self.deploy_test_safe(
            number_owners=3, threshold=2, initial_funding_wei=initial_funding
        )
        my_safe_address = safe.address

        response = self.client.post(
            reverse("v2:safe-multisig-tx-estimate", args=(my_safe_address,)),
            data=data,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Use non existing Safe
        non_existing_safe_address = Account.create().address
        response = self.client.post(
            reverse("v2:safe-multisig-tx-estimate", args=(non_existing_safe_address,)),
            data=data,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertIn("SafeDoesNotExist", response.data["exception"])

        # Add to database and test again
        SafeContractFactory(address=my_safe_address)
        response = self.client.post(
            reverse("v2:safe-multisig-tx-estimate", args=(my_safe_address,)),
            data=data,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response_json = response.json()
        for field in ("safeTxGas", "dataGas", "gasPrice"):
            self.assertTrue(isinstance(response_json[field], str))
            self.assertGreater(int(response_json[field]), 0)

        expected_refund_receiver = Account.from_key(
            settings.SAFE_TX_SENDER_PRIVATE_KEY
        ).address
        self.assertIsNone(response_json["lastUsedNonce"])
        self.assertEqual(response_json["gasToken"], NULL_ADDRESS)
        self.assertEqual(response_json["refundReceiver"], expected_refund_receiver)

        to = Account.create().address
        data = {"to": to, "value": initial_funding // 2, "data": None, "operation": 0}
        response = self.client.post(
            reverse("v2:safe-multisig-tx-estimate", args=(my_safe_address,)),
            data=data,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["refund_receiver"], expected_refund_receiver)

        data = {"to": to, "value": initial_funding // 2, "data": None, "operation": 2}
        response = self.client.post(
            reverse("v2:safe-multisig-tx-estimate", args=(my_safe_address,)),
            data=data,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn(
            "Please use Gnosis Safe CreateLib", str(response.data["non_field_errors"])
        )

    def test_safe_signal_v2(self):
        safe_address = Account.create().address

        response = self.client.get(reverse("v2:safe-signal", args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.put(reverse("v2:safe-signal", args=(safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        invalid_address = get_eth_address_with_invalid_checksum()

        response = self.client.get(reverse("v2:safe-signal", args=(invalid_address,)))
        self.assertEqual(response.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        # We need ether or task will be hanged because of problems with retries emulating celery tasks during testing
        safe_creation2 = self.create2_test_safe_in_db()
        self.assertIsNone(safe_creation2.tx_hash)
        self.assertIsNone(safe_creation2.block_number)
        my_safe_address = safe_creation2.safe.address

        response = self.client.get(reverse("v2:safe-signal", args=(my_safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["txHash"])
        self.assertIsNone(response.json()["blockNumber"])

        self.send_ether(my_safe_address, safe_creation2.payment)
        response = self.client.put(reverse("v2:safe-signal", args=(my_safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertTrue(self.ethereum_client.is_contract(my_safe_address))
        safe_creation2.refresh_from_db()
        self.assertIsNotNone(safe_creation2.tx_hash)

        response = self.client.get(reverse("v2:safe-signal", args=(my_safe_address,)))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["txHash"], safe_creation2.tx_hash)
        self.assertEqual(response.json()["blockNumber"], safe_creation2.block_number)
