import factory
from factory.django import DjangoModelFactory

from gnosis.eth.utils import get_eth_address_with_key

from .. import models


class PriceOracleFactory(DjangoModelFactory):
    class Meta:
        model = models.PriceOracle

    name = factory.Faker("company")


class TokenFactory(DjangoModelFactory):
    class Meta:
        model = models.Token

    address = factory.LazyFunction(lambda: get_eth_address_with_key()[0])
    name = factory.Faker("cryptocurrency_name")
    symbol = factory.Faker("cryptocurrency_code")
    description = factory.Faker("catch_phrase")
    decimals = 18
    logo_uri = ""
    website_uri = ""
    gas = True
    fixed_eth_conversion = 1


class PriceOracleTickerFactory(DjangoModelFactory):
    class Meta:
        model = models.PriceOracleTicker

    price_oracle = factory.SubFactory(PriceOracleFactory)
    token = factory.SubFactory(TokenFactory)
    ticker = factory.Faker("cryptocurrency_code")
    inverse = False
