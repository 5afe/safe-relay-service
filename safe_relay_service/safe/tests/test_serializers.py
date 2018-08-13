from django.test import TestCase
from django_eth.tests.factories import get_eth_address_with_key
from ethereum.transactions import secpk1n
from faker import Faker
from hexbytes import HexBytes

from ..models import SafeContract, SafeFunding
from ..safe_service import SafeServiceProvider
from ..serializers import (SafeCreationSerializer,
                           SafeFundingResponseSerializer,
                           SafeMultisigEstimateTxSerializer,
                           SafeMultisigTxSerializer)
from .factories import generate_safe

faker = Faker()


class TestSerializers(TestCase):

    def test_generic_serializer(self):
        owner1, _ = get_eth_address_with_key()
        owner2, _ = get_eth_address_with_key()
        owner3, _ = get_eth_address_with_key()
        invalid_checksumed_address = '0xb299182d99e65703f0076e4812653aab85fca0f0'

        owners = [owner1, owner2, owner3]
        data = {'s': secpk1n // 2,
                'owners': owners,
                'threshold': len(owners)}
        self.assertTrue(SafeCreationSerializer(data=data).is_valid())

        data = {'s': secpk1n // 2,
                'owners': owners,
                'threshold': len(owners) + 1}
        self.assertFalse(SafeCreationSerializer(data=data).is_valid())

        data = {'s': secpk1n // 2,
                'owners': owners + [invalid_checksumed_address],
                'threshold': len(owners)}
        self.assertFalse(SafeCreationSerializer(data=data).is_valid())

        data = {'s': secpk1n // 2,
                'owners': [],
                'threshold': len(owners)}
        self.assertFalse(SafeCreationSerializer(data=data).is_valid())

    def test_funding_serializer(self):
        owner1, _ = get_eth_address_with_key()
        safe_contract = SafeContract.objects.create(address=owner1, master_copy='0x' + '0' * 40)
        safe_funding = SafeFunding.objects.create(safe=safe_contract)

        s = SafeFundingResponseSerializer(safe_funding)

        self.assertTrue(s.data)

    def test_safe_multisig_tx_serializer(self):
        safe_service = SafeServiceProvider()
        w3 = safe_service.w3

        safe = generate_safe(number_owners=3).safe.address
        to = None
        value = int(10e18)
        tx_data = None
        operation = 0
        safe_tx_gas = 1
        data_gas = 1
        gas_price = 1
        gas_token = None
        nonce = 0

        data = {
            "safe": safe,
            "to": to,
            "value": value,  # 1 ether
            "data": tx_data,
            "operation": operation,
            "safe_tx_gas": safe_tx_gas,
            "data_gas": data_gas,
            "gas_price": gas_price,
            "gas_token": gas_token,
            "nonce": nonce,
            "signatures": [
                {
                    'r': 5,
                    's': 7,
                    'v': 27
                },
                {
                    'r': 17,
                    's': 29,
                    'v': 28
                }]}
        serializer = SafeMultisigTxSerializer(data=data)
        self.assertFalse(serializer.is_valid())  # Less signatures than threshold

        owners_with_keys = [get_eth_address_with_key(), get_eth_address_with_key()]
        # Signatures must be sorted!
        owners_with_keys.sort(key=lambda x: x[0].lower())
        owners = [x[0] for x in owners_with_keys]
        keys = [x[1] for x in owners_with_keys]

        safe = generate_safe(owners=owners).safe.address
        data['safe'] = safe

        serializer = SafeMultisigTxSerializer(data=data)
        self.assertFalse(serializer.is_valid())  # To and data cannot both be null

        tx_data = HexBytes('0xabcd')
        data['data'] = tx_data.hex()
        serializer = SafeMultisigTxSerializer(data=data)
        self.assertFalse(serializer.is_valid())  # Operation is not create, but no to provided

        # Now we fix the signatures
        to = owners[-1]
        data['to'] = to
        multisig_tx_hash = safe_service.get_hash_for_safe_tx(
            safe,
            to,
            value,
            tx_data,
            operation,
            safe_tx_gas,
            data_gas,
            gas_price,
            gas_token,
            nonce
        )
        signatures = [w3.eth.account.signHash(multisig_tx_hash, private_key) for private_key in keys]
        data['signatures'] = signatures
        serializer = SafeMultisigTxSerializer(data=data)
        self.assertTrue(serializer.is_valid())

    def test_safe_multisig_tx_estimate_serializer(self):
        safe_address, _ = get_eth_address_with_key()
        eth_address, _ = get_eth_address_with_key()
        data = {
            'safe': safe_address,
            'to': None,
            'data': None,
            'value': 1,
            'operation': 0
        }
        serializer = SafeMultisigEstimateTxSerializer(data=data)

        # To and data cannot be empty
        self.assertFalse(serializer.is_valid())

        data = {
            'safe': safe_address,
            'to': eth_address,
            'data': '0x00',
            'value': 1,
            'operation': 2
        }
        serializer = SafeMultisigEstimateTxSerializer(data=data)
        # Operation cannot be contract creation and to set
        self.assertFalse(serializer.is_valid())

        data = {
            'safe': safe_address,
            'to': None,
            'data': None,
            'value': 1,
            'operation': 2
        }
        serializer = SafeMultisigEstimateTxSerializer(data=data)
        # Operation is not contract creation and to is not empty
        self.assertFalse(serializer.is_valid())

        data = {
            'safe': safe_address,
            'to': eth_address,
            'data': '0x00',
            'value': 1,
            'operation': 0
        }
        serializer = SafeMultisigEstimateTxSerializer(data=data)
        # Operation is not contract creation and to is not empty
        self.assertTrue(serializer.is_valid())

        data = {
            'safe': safe_address,
            'to': None,
            'data': '0x00',
            'value': 1,
            'operation': 2
        }
        serializer = SafeMultisigEstimateTxSerializer(data=data)
        # Operation is not contract creation and to is not empty
        self.assertTrue(serializer.is_valid())
