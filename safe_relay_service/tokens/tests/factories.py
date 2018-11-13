import factory as factory_boy

from django_eth.tests.factories import get_eth_address_with_key

from .. import models


class TokenFactory(factory_boy.DjangoModelFactory):

    class Meta:
        model = models.Token

    address = get_eth_address_with_key()[0]
    name = factory_boy.Faker('cryptocurrency_name')
    symbol = factory_boy.Faker('cryptocurrency_code')
    description = factory_boy.Faker('catch_phrase')
    decimals = 18
    logo_uri = ''
    website_uri = ''
    gas_token = True
    fixed_eth_conversion = 1
