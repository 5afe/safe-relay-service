from django.urls import reverse
from faker import Faker
from rest_framework import status
from rest_framework.test import APITestCase

from safe_relay_service.ether.tests.factories import get_eth_address_with_key

faker = Faker()


class TestViews(APITestCase):

    def test_about(self):
        request = self.client.get(reverse('v1:about'))
        self.assertEquals(request.status_code, status.HTTP_200_OK)
