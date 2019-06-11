from django.test import TestCase

from ..models import GasPrice
from .factories import GasPriceFactory


class TestModels(TestCase):
    def test_gas_price(self):
        gas_price_oldest = GasPriceFactory()
        gas_price_newest = GasPriceFactory()

        self.assertEqual(gas_price_oldest, GasPrice.objects.earliest())
        self.assertEqual(gas_price_newest, GasPrice.objects.last())
