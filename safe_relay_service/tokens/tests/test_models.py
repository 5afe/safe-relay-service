from django.test import TestCase

from ..exchanges import CannotGetTokenPriceFromApi
from ..models import PriceOracle
from .factories import (PriceOracleFactory, PriceOracleTickerFactory,
                        TokenFactory)


class TestModels(TestCase):
    def test_price_oracles(self):
        self.assertEqual(PriceOracle.objects.count(), 4)

    def test_token_eth_value(self):
        price_oracle = PriceOracle.objects.get(name='DutchX')
        token = TokenFactory(fixed_eth_conversion=None)
        with self.assertRaises(CannotGetTokenPriceFromApi):
            token.get_eth_value()
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
        PriceOracleTickerFactory(token=token, price_oracle=price_oracle, ticker='BADTICKER')
        with self.assertRaises(CannotGetTokenPriceFromApi):
            token.get_eth_value()

    def test_token_eth_value_inverted(self):
        price_oracle = PriceOracle.objects.get(name='DutchX')

        token = TokenFactory(fixed_eth_conversion=None)
        PriceOracleTickerFactory(token=token, price_oracle=price_oracle, ticker='RDN-WETH')
        price = token.get_eth_value()

        token = TokenFactory(fixed_eth_conversion=None)
        PriceOracleTickerFactory(token=token, price_oracle=price_oracle, ticker='RDN-WETH', inverse=True)
        price_inverted = token.get_eth_value()

        self.assertEqual(1 / price, price_inverted)

    def test_token_eth_value_with_fixed_conversion(self):
        fixed_eth_conversion = 0.1
        token = TokenFactory(fixed_eth_conversion=fixed_eth_conversion)
        self.assertEqual(token.get_eth_value(), fixed_eth_conversion)

        token = TokenFactory(decimals=17, fixed_eth_conversion=fixed_eth_conversion)
        self.assertEqual(token.get_eth_value(), fixed_eth_conversion * 10)

        token = TokenFactory(decimals=19, fixed_eth_conversion=fixed_eth_conversion)
        self.assertEqual(token.get_eth_value(), fixed_eth_conversion / 10)
