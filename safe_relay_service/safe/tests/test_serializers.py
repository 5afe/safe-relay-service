from django.test import TestCase
from ethereum.transactions import secpk1n
from faker import Faker

from safe_relay_service.ether.tests.factories import get_eth_address_with_key

from ..serializers import SafeTransactionCreationSerializer

faker = Faker()


class TestSerializers(TestCase):

    def test_generic_serializer(self):
        owner1, _ = get_eth_address_with_key()
        owner2, _ = get_eth_address_with_key()
        owner3, _ = get_eth_address_with_key()
        invalid_checksumed_address = '0xb299182d99e65703f0076e4812653aab85fca0f0'

        owners = [owner1, owner2, owner3]
        data = {'s': secpk1n - 5,
                'owners': owners,
                'threshold': len(owners)}
        self.assertTrue(SafeTransactionCreationSerializer(data=data).is_valid())

        data = {'s': secpk1n - 5,
                'owners': owners,
                'threshold': len(owners) + 1}
        self.assertFalse(SafeTransactionCreationSerializer(data=data).is_valid())

        data = {'s': secpk1n - 5,
                'owners': owners + [invalid_checksumed_address],
                'threshold': len(owners)}
        self.assertFalse(SafeTransactionCreationSerializer(data=data).is_valid())

        data = {'s': secpk1n - 5,
                'owners': [],
                'threshold': len(owners)}
        self.assertFalse(SafeTransactionCreationSerializer(data=data).is_valid())
