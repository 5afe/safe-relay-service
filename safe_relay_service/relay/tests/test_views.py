import logging

from django.urls import reverse
from django_eth.constants import NULL_ADDRESS
from django_eth.tests.factories import (get_eth_address_with_invalid_checksum,
                                        get_eth_address_with_key)
from faker import Faker
from gnosis.safe.safe_service import SafeServiceProvider
from rest_framework import status
from rest_framework.test import APITestCase

from ..models import SafeContract, SafeCreation, SafeMultisigTx
from ..serializers import SafeCreationSerializer
from .factories import deploy_safe, generate_safe, generate_valid_s
from .safe_test_case import TestCaseWithSafeContractMixin

faker = Faker()

logger = logging.getLogger(__name__)


class TestViews(APITestCase, TestCaseWithSafeContractMixin):
    @classmethod
    def setUpTestData(cls):
        cls.prepare_safe_tests()

    def test_about(self):
        request = self.client.get(reverse('v1:about'))
        self.assertEqual(request.status_code, status.HTTP_200_OK)

    def test_gas_station(self):
        request = self.client.get(reverse('v1:gas-station'))
        self.assertEqual(request.status_code, status.HTTP_200_OK)

    def test_safe_creation(self):
        s = generate_valid_s()
        owner1, _ = get_eth_address_with_key()
        owner2, _ = get_eth_address_with_key()
        serializer = SafeCreationSerializer(data={
            's': s,
            'owners': [owner1, owner2],
            'threshold': 2
        })
        self.assertTrue(serializer.is_valid())
        request = self.client.post(reverse('v1:safes'), data=serializer.data, format='json')

        self.assertEqual(request.status_code, status.HTTP_201_CREATED)

        self.assertTrue(SafeContract.objects.filter(address=request.data['safe']))

        self.assertTrue(SafeCreation.objects.filter(owners__contains=[owner1]))

        serializer = SafeCreationSerializer(data={
            's': -1,
            'owners': [owner1, owner2],
            'threshold': 2
        })
        self.assertFalse(serializer.is_valid())
        request = self.client.post(reverse('v1:safes'), data=serializer.data, format='json')
        self.assertEqual(request.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

    def test_safe_multisig_tx(self):
        # Create Safe ------------------------------------------------
        safe_service = SafeServiceProvider()
        w3 = safe_service.w3
        funder = w3.eth.accounts[0]
        owners_with_keys = [get_eth_address_with_key(), get_eth_address_with_key()]

        # Signatures must be sorted!
        owners_with_keys.sort(key=lambda x: x[0].lower())
        owners = [x[0] for x in owners_with_keys]
        keys = [x[1] for x in owners_with_keys]
        threshold = len(owners_with_keys)

        safe_creation = generate_safe(owners=owners, threshold=threshold)
        my_safe_address = deploy_safe(w3, safe_creation, funder)

        # Send something to the safe
        safe_balance = w3.toWei(0.01, 'ether')
        w3.eth.waitForTransactionReceipt(w3.eth.sendTransaction({
            'from': funder,
            'to': my_safe_address,
            'value': safe_balance
        }))

        # Send something to the owner[0], who will be sending the tx
        owner0_balance = safe_balance
        w3.eth.waitForTransactionReceipt(w3.eth.sendTransaction({
            'from': funder,
            'to': owners[0],
            'value': owner0_balance
        }))
        # Safe prepared --------------------------------------------
        to, _ = get_eth_address_with_key()
        value = safe_balance // 2
        tx_data = None
        operation = 0
        refund_receiver = None
        nonce = 0

        data = {
            "to": to,
            "value": value,
            "data": tx_data,
            "operation": operation,
        }

        # Get estimation for gas
        request = self.client.post(reverse('v1:safe-multisig-tx-estimate', args=(my_safe_address,)),
                                   data=data,
                                   format='json')
        self.assertEqual(request.status_code, status.HTTP_200_OK)
        estimation_json = request.json()

        safe_tx_gas = estimation_json['safeTxGas'] + estimation_json['signatureGas']
        data_gas = estimation_json['dataGas']
        gas_price = estimation_json['gasPrice']
        gas_token = estimation_json['gasToken']

        multisig_tx_hash = safe_service.get_hash_for_safe_tx(
            my_safe_address,
            to,
            value,
            tx_data,
            operation,
            safe_tx_gas,
            data_gas,
            gas_price,
            gas_token,
            refund_receiver,
            nonce
        )
        signatures = [w3.eth.account.signHash(multisig_tx_hash, private_key) for private_key in keys]
        signatures_json = [{'v': s['v'], 'r': s['r'], 's': s['s']} for s in signatures]

        data = {
            "to": to,
            "value": value,
            "data": tx_data,
            "operation": operation,
            "safe_tx_gas": safe_tx_gas,
            "data_gas": data_gas,
            "gas_price": gas_price,
            "gas_token": gas_token,
            "nonce": nonce,
            "signatures": signatures_json
        }

        request = self.client.post(reverse('v1:safe-multisig-tx', args=(my_safe_address,)),
                                   data=data,
                                   format='json')
        self.assertEqual(request.status_code, status.HTTP_201_CREATED)
        tx_hash = request.json()['transactionHash'][2:]  # Remove leading 0x
        safe_multisig_tx = SafeMultisigTx.objects.get(tx_hash=tx_hash)
        self.assertEqual(safe_multisig_tx.to, to)
        self.assertEqual(safe_multisig_tx.value, value)
        self.assertEqual(safe_multisig_tx.data, tx_data)
        self.assertEqual(safe_multisig_tx.operation, operation)
        self.assertEqual(safe_multisig_tx.safe_tx_gas, safe_tx_gas)
        self.assertEqual(safe_multisig_tx.data_gas, data_gas)
        self.assertEqual(safe_multisig_tx.gas_price, gas_price)
        self.assertEqual(safe_multisig_tx.gas_token, gas_token)
        self.assertEqual(safe_multisig_tx.nonce, nonce)
        signature_pairs = [(s['v'], s['r'], s['s']) for s in signatures]
        signatures_packed = safe_service.signatures_to_bytes(signature_pairs)
        self.assertEqual(bytes(safe_multisig_tx.signatures), signatures_packed)

        # Send the same tx again
        request = self.client.post(reverse('v1:safe-multisig-tx', args=(my_safe_address,)),
                                   data=data,
                                   format='json')
        self.assertEqual(request.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)
        self.assertTrue('exists' in request.data)

    def test_safe_multisig_tx_errors(self):
        my_safe_address = get_eth_address_with_invalid_checksum()
        request = self.client.post(reverse('v1:safe-multisig-tx', args=(my_safe_address,)),
                                   data={},
                                   format='json')
        self.assertEqual(request.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        my_safe_address, _ = get_eth_address_with_key()
        request = self.client.post(reverse('v1:safe-multisig-tx', args=(my_safe_address,)),
                                   data={},
                                   format='json')
        self.assertEqual(request.status_code, status.HTTP_404_NOT_FOUND)

        my_safe_address = generate_safe().safe.address
        request = self.client.post(reverse('v1:safe-multisig-tx', args=(my_safe_address,)),
                                   data={},
                                   format='json')
        self.assertEqual(request.status_code, status.HTTP_400_BAD_REQUEST)

    def test_safe_multisig_tx_estimate(self):
        my_safe_address = get_eth_address_with_invalid_checksum()
        request = self.client.post(reverse('v1:safe-multisig-tx-estimate', args=(my_safe_address,)),
                                   data={},
                                   format='json')
        self.assertEqual(request.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        my_safe_address, _ = get_eth_address_with_key()
        request = self.client.post(reverse('v1:safe-multisig-tx-estimate', args=(my_safe_address,)),
                                   data={},
                                   format='json')
        self.assertEqual(request.status_code, status.HTTP_404_NOT_FOUND)

        to, _ = get_eth_address_with_key()
        data = {
            'to': to,
            'value': 10,
            'data': '0x',
            'operation': 1
        }

        safe_creation = generate_safe()
        my_safe_address = deploy_safe(self.w3, safe_creation, self.w3.eth.accounts[0])

        request = self.client.post(reverse('v1:safe-multisig-tx-estimate', args=(my_safe_address,)),
                                   data=data,
                                   format='json')
        self.assertEqual(request.status_code, status.HTTP_200_OK)
        response = request.json()
        self.assertGreater(response['safeTxGas'], 0)
        self.assertGreater(response['dataGas'], 0)
        self.assertGreater(response['gasPrice'], 0)
        self.assertGreaterEqual(response['nonce'], 0)
        self.assertEqual(response['gasToken'], NULL_ADDRESS)

        to, _ = get_eth_address_with_key()
        data = {
            'to': to,
            'value': 100,
            'data': None,
            'operation': 0
        }
        request = self.client.post(reverse('v1:safe-multisig-tx-estimate', args=(my_safe_address,)),
                                   data=data,
                                   format='json')
        self.assertEqual(request.status_code, status.HTTP_200_OK)

    def test_safe_signal(self):
        safe_address, _ = get_eth_address_with_key()

        request = self.client.get(reverse('v1:safe-signal', args=(safe_address,)))
        self.assertEqual(request.status_code, status.HTTP_404_NOT_FOUND)

        invalid_address = get_eth_address_with_invalid_checksum()

        request = self.client.get(reverse('v1:safe-signal', args=(invalid_address,)))
        self.assertEqual(request.status_code, status.HTTP_422_UNPROCESSABLE_ENTITY)

        my_safe_address = generate_safe().safe.address
        request = self.client.post(reverse('v1:safe-multisig-tx', args=(my_safe_address,)),
                                   data={},
                                   format='json')
        self.assertEqual(request.status_code, status.HTTP_400_BAD_REQUEST)
