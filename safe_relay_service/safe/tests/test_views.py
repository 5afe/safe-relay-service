import json

from django.urls import reverse
from faker import Faker
from rest_framework import status
from rest_framework.test import APITestCase

from safe_relay_service.ether.tests.factories import get_eth_address_with_key

from ..models import SafeContract, SafeCreation
from ..serializers import SafeTransactionCreationSerializer
from .factories import generate_valid_s

faker = Faker()


class TestViews(APITestCase):

    def test_about(self):
        request = self.client.get(reverse('v1:about'))
        self.assertEqual(request.status_code, status.HTTP_200_OK)

    def test_safe_creation(self):
        s = generate_valid_s()
        owner1, _ = get_eth_address_with_key()
        owner2, _ = get_eth_address_with_key()
        serializer = SafeTransactionCreationSerializer(data={
            's': s,
            'owners': [owner1, owner2],
            'threshold': 2
        })
        self.assertTrue(serializer.is_valid())
        request = self.client.post(reverse('v1:safes'), data=json.dumps(serializer.data),
                                   content_type='application/json')

        self.assertEqual(request.status_code, status.HTTP_201_CREATED)

        self.assertTrue(SafeContract.objects.filter(address=request.data['safe']))

        self.assertTrue(SafeCreation.objects.filter(owners__contains=[owner1]))
