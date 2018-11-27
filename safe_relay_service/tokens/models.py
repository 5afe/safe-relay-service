import math

import requests
from django.db import models
from django_eth.models import EthereumAddressField


class CannotGetTokenPriceFromApi(Exception):
    pass


class Token(models.Model):
    address = EthereumAddressField(primary_key=True)
    name = models.CharField(max_length=30)
    symbol = models.CharField(max_length=30)
    description = models.TextField(blank=True)
    decimals = models.PositiveSmallIntegerField()
    logo_uri = models.URLField(blank=True)
    website_uri = models.URLField(blank=True)
    gas = models.BooleanField(default=False)
    fixed_eth_conversion = models.DecimalField(null=True, default=None, max_digits=25, decimal_places=15)
    relevance = models.PositiveIntegerField(default=1)

    def __str__(self):
        return '%s - %s' % (self.name, self.address)

    # TODO Cache
    def get_eth_value(self) -> float:
        if not self.fixed_eth_conversion:  # None or 0 ignored
            pair = '{}ETH'.format(self.symbol)
            api_json = requests.get('https://api.kraken.com/0/public/Ticker?pair=' + pair).json()
            error = api_json.get('error')
            if error:
                raise CannotGetTokenPriceFromApi(str(api_json['error']))
            price = float(api_json['result'][pair]['c'][0])
            return price
        else:
            # Ether has 18 decimals, but maybe the token has a different number
            multiplier = 1e18 / 10**self.decimals
            return round(multiplier * float(self.fixed_eth_conversion), 10)

    def calculate_gas_price(self, gas_price: int, price_margin: float=1.0) -> int:
        """
        Converts ether gas price to token's gas price
        :param gas_price: Regular ether gas price
        :param price_margin: Threshold to estimate a little higher, so tx will
        not be rejected in a few minutes
        :return:
        """
        return math.ceil(gas_price / self.get_eth_value() * price_margin)

    def get_full_logo_url(self):
        return 'https://raw.githubusercontent.com/rmeissner/crypto_resources/' \
               'master/tokens/mainnet/icons/{}.png'.format(self.address)
