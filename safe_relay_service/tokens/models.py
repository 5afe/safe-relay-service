import math

from django.db import models
from django_eth.models import EthereumAddressField

from .exchanges import get_price_oracle, CannotGetTokenPriceFromApi


class PriceOracle(models.Model):
    name = models.CharField(max_length=50, unique=True)


class PriceOracleTicker(models.Model):
    price_oracle = models.ForeignKey(PriceOracle, null=True, on_delete=models.CASCADE)
    token = models.ForeignKey('Token', null=True, on_delete=models.CASCADE)
    ticker = models.CharField(max_length=90, blank=True)


class Token(models.Model):
    address = EthereumAddressField(primary_key=True)
    name = models.CharField(max_length=30)
    symbol = models.CharField(max_length=30)
    description = models.TextField(blank=True)
    decimals = models.PositiveSmallIntegerField()
    logo_uri = models.URLField(blank=True)
    website_uri = models.URLField(blank=True)
    gas = models.BooleanField(default=False)
    price_oracles = models.ManyToManyField(PriceOracle, through=PriceOracleTicker)
    fixed_eth_conversion = models.DecimalField(null=True, default=None, max_digits=25, decimal_places=15)
    relevance = models.PositiveIntegerField(default=1)

    def __str__(self):
        return '%s - %s' % (self.name, self.address)

    # TODO Cache
    def get_eth_value(self) -> float:
        if not self.fixed_eth_conversion:  # None or 0 ignored
            prices = []
            # Get the average price of the price oracles
            for price_oracle_ticker in self.price_oracles:
                price_oracle_name = price_oracle_ticker.price_oracle.name
                ticker = price_oracle_ticker.ticker
                try:
                    prices.append(get_price_oracle(price_oracle_name).get_price(ticker))
                except CannotGetTokenPriceFromApi:
                    pass
            return sum(prices) / len(prices)
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


