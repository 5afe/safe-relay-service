import math

import requests
from django.db import models

from django_eth.models import EthereumAddressField


class Token(models.Model):
    address = EthereumAddressField(primary_key=True)
    name = models.CharField(max_length=15)
    code = models.CharField(max_length=5)
    description = models.TextField(blank=True)
    decimals = models.PositiveSmallIntegerField()
    logo_uri = models.URLField(blank=True)
    website_uri = models.URLField(blank=True)
    gas_token = models.BooleanField(default=False)
    fixed_eth_conversion = models.DecimalField(null=True, default=None, max_digits=25, decimal_places=15)

    def __str__(self):
        return '%s - %s' % (self.name, self.address)

    # TODO Cache
    def get_eth_value(self) -> float:
        if self.fixed_eth_conversion is None:
            pair = '{}ETH'.format(self.symbol)
            price = float(requests.get('https://api.kraken.com/0/public/Ticker?pair=' + pair).json()['result']['c'][0])
            return price
        else:
            return float(self.fixed_eth_conversion)

    def calculate_gas_price(self, gas_price: int, price_margin: float=1.0) -> int:
        """
        Converts ether gas price to token's gas price
        :param gas_price: Regular ether gas price
        :param price_margin: Threshold to estimate a little higher, so tx will
        not be rejected in a few minutes
        :return:
        """
        return math.ceil(gas_price / self.get_eth_value() * price_margin)
