from django.test import TestCase

from ..models import PriceOracle
from ..exchanges import CannotGetTokenPriceFromApi
from .factories import TokenFactory, PriceOracleTickerFactory, PriceOracleFactory


class TestModels(TestCase):
    def test_price_oracles(self):
        self.assertEqual(PriceOracle.objects.count(), 3)

    def test_token_eth_value(self):
        fixed_eth_conversion = 0.1
        token = TokenFactory(fixed_eth_conversion=fixed_eth_conversion)
        self.assertEqual(token.get_eth_value(), fixed_eth_conversion)

        token = TokenFactory(decimals=17, fixed_eth_conversion=fixed_eth_conversion)
        self.assertEqual(token.get_eth_value(), fixed_eth_conversion * 10)

        token = TokenFactory(decimals=19, fixed_eth_conversion=fixed_eth_conversion)
        self.assertEqual(token.get_eth_value(), fixed_eth_conversion / 10)

    def test_token_eth_price(self):
        token = TokenFactory(fixed_eth_conversion=None)
        with self.assertRaises(CannotGetTokenPriceFromApi):
            token.get_eth_value()
        price_oracle = PriceOracle.objects.get(name='DutchX')
        PriceOracleTickerFactory(token=token, price_oracle=price_oracle, ticker='RDN-WETH')
        price = token.get_eth_value()
        self.assertIsInstance(price, float)
        self.assertGreater(price, .0)
        PriceOracleTickerFactory(token=token, price_oracle=price_oracle, ticker='BADTICKER')
        price = token.get_eth_value()
        self.assertIsInstance(price, float)
        self.assertGreater(price, .0)

        token = TokenFactory(fixed_eth_conversion=None)
        with self.assertRaises(CannotGetTokenPriceFromApi):
            token.get_eth_value()
        price_oracle = PriceOracle.objects.get(name='DutchX')
        PriceOracleTickerFactory(token=token, price_oracle=price_oracle, ticker='BADTICKER')
        with self.assertRaises(CannotGetTokenPriceFromApi):
            token.get_eth_value()
