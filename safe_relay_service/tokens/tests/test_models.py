from urllib.parse import urljoin

from django.conf import settings
from django.test import TestCase

from web3 import Web3

from ..models import PriceOracle
from ..price_oracles import CannotGetTokenPriceFromApi
from .factories import PriceOracleTickerFactory, TokenFactory


class TestModels(TestCase):
    def test_price_oracles(self):
        self.assertEqual(PriceOracle.objects.count(), 4)

    def test_token_calculate_payment(self):
        token = TokenFactory(fixed_eth_conversion=0.1)
        self.assertEqual(token.calculate_payment(Web3.toWei(1, 'ether')), Web3.toWei(10, 'ether'))

        token = TokenFactory(fixed_eth_conversion=1.0)
        self.assertEqual(token.calculate_payment(Web3.toWei(1, 'ether')), Web3.toWei(1, 'ether'))

        token = TokenFactory(fixed_eth_conversion=2.0)
        self.assertEqual(token.calculate_payment(Web3.toWei(1, 'ether')), Web3.toWei(0.5, 'ether'))

        token = TokenFactory(fixed_eth_conversion=10.0)
        self.assertEqual(token.calculate_payment(Web3.toWei(1, 'ether')), Web3.toWei(0.1, 'ether'))

        token = TokenFactory(fixed_eth_conversion=0.6512)
        self.assertEqual(token.calculate_payment(Web3.toWei(1.23, 'ether')), 1888820638820638720)

        token = TokenFactory(fixed_eth_conversion=1.0, decimals=17)
        self.assertEqual(token.calculate_payment(Web3.toWei(1, 'ether')), Web3.toWei(0.1, 'ether'))

    def test_token_eth_value(self):
        price_oracle = PriceOracle.objects.get(name='DutchX')
        token = TokenFactory(fixed_eth_conversion=None)
        with self.assertRaises(CannotGetTokenPriceFromApi):
            token.get_eth_value()
        PriceOracleTickerFactory(token=token, price_oracle=price_oracle, ticker='0x543Ff227F64Aa17eA132Bf9886cAb5DB55DCAddf-WETH')
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
        PriceOracleTickerFactory(token=token, price_oracle=price_oracle, ticker='0x543Ff227F64Aa17eA132Bf9886cAb5DB55DCAddf-WETH')
        price = token.get_eth_value()

        token = TokenFactory(fixed_eth_conversion=None)
        PriceOracleTickerFactory(token=token, price_oracle=price_oracle, ticker='0x543Ff227F64Aa17eA132Bf9886cAb5DB55DCAddf-WETH', inverse=True)
        price_inverted = token.get_eth_value()

        self.assertAlmostEqual(1 / price, price_inverted, delta=10.0)

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
