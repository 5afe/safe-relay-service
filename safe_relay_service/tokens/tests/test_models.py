from urllib.parse import urljoin, urlparse

from django.conf import settings
from django.test import TestCase

from ..exchanges import CannotGetTokenPriceFromApi
from ..models import PriceOracle
from .factories import PriceOracleTickerFactory, TokenFactory


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

        self.assertAlmostEqual(1 / price, price_inverted, delta=1.0)

    def test_token_eth_value_with_fixed_conversion(self):
        fixed_eth_conversion = 0.1
        token = TokenFactory(fixed_eth_conversion=fixed_eth_conversion)
        self.assertEqual(token.get_eth_value(), fixed_eth_conversion)

        token = TokenFactory(decimals=17, fixed_eth_conversion=fixed_eth_conversion)
        self.assertEqual(token.get_eth_value(), fixed_eth_conversion * 10)

        token = TokenFactory(decimals=19, fixed_eth_conversion=fixed_eth_conversion)
        self.assertEqual(token.get_eth_value(), fixed_eth_conversion / 10)

    def test_token_logo_uri(self):
        logo_uri = ''
        token = TokenFactory(logo_uri=logo_uri)
        self.assertEqual(token.get_full_logo_uri(),
                         urljoin(settings.TOKEN_LOGO_BASE_URI, token.address + settings.TOKEN_LOGO_EXTENSION))

        logo_uri = 'hola.gif'
        token = TokenFactory(logo_uri=logo_uri)
        self.assertEqual(token.get_full_logo_uri(), urljoin(settings.TOKEN_LOGO_BASE_URI, token.logo_uri))

        logo_uri = 'http://absoluteurl.com/file.jpg'
        token = TokenFactory(logo_uri=logo_uri)
        self.assertEqual(token.get_full_logo_uri(), logo_uri)
