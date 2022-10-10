import logging
import math
from typing import Optional
from urllib.parse import urljoin, urlparse

from django.conf import settings
from django.db import models
from django.db.models import JSONField

from gnosis.eth.django.models import EthereumAddressField

from .price_oracles import (
    CannotGetTokenPriceFromApi,
    ExchangeApiException,
    get_price_oracle,
)

logger = logging.getLogger(__name__)


class PriceOracle(models.Model):
    name = models.CharField(max_length=50, unique=True)
    configuration = JSONField(null=False, default=dict)

    def __str__(self):
        return f"{self.name} configuration={self.configuration}"


class PriceOracleTicker(models.Model):
    price_oracle = models.ForeignKey(
        PriceOracle, null=True, on_delete=models.CASCADE, related_name="tickers"
    )
    token = models.ForeignKey(
        "Token",
        null=True,
        on_delete=models.CASCADE,
        related_name="price_oracle_tickers",
    )
    ticker = models.CharField(max_length=90, blank=False, null=False)
    inverse = models.BooleanField(default=False)

    def __str__(self):
        return "%s - %s - %s - Inverse %s" % (
            self.price_oracle.name,
            self.token.symbol,
            self.ticker,
            self.inverse,
        )

    def _price(self) -> Optional[float]:
        try:
            price = get_price_oracle(
                self.price_oracle.name, self.price_oracle.configuration
            ).get_price(self.ticker)
            if price and self.inverse:  # Avoid 1 / 0
                price = 1 / price
        except ExchangeApiException:
            logger.warning(
                "Cannot get price for %s - %s",
                self.price_oracle.name,
                self.ticker,
                exc_info=True,
            )
            price = None
        return price

    price = property(_price)


class TokenQuerySet(models.QuerySet):
    def gas_tokens(self):
        return self.filter(gas=True)


class Token(models.Model):
    objects = TokenQuerySet.as_manager()
    address = EthereumAddressField(primary_key=True)
    name = models.CharField(max_length=60)
    symbol = models.CharField(max_length=60)
    description = models.TextField(blank=True)
    decimals = models.PositiveSmallIntegerField()
    logo_uri = models.CharField(blank=True, max_length=300)
    website_uri = models.URLField(blank=True)
    gas = models.BooleanField(default=False)
    price_oracles = models.ManyToManyField(PriceOracle, through=PriceOracleTicker)
    fixed_eth_conversion = models.DecimalField(
        null=True, default=None, blank=True, max_digits=25, decimal_places=15
    )
    relevance = models.PositiveIntegerField(default=100)

    def __str__(self):
        return "%s - %s" % (self.name, self.address)

    def get_eth_value(self) -> float:
        multiplier = 1e18 / 10**self.decimals
        if self.fixed_eth_conversion:  # `None` or `0` are ignored
            # Ether has 18 decimals, but maybe the token has a different number
            return round(multiplier * float(self.fixed_eth_conversion), 10)
        else:
            prices = [
                price_oracle_ticker.price
                for price_oracle_ticker in self.price_oracle_tickers.all()
            ]
            prices = [price for price in prices if price is not None and price > 0]
            if prices:
                # Get the average price of the price oracles
                return multiplier * (sum(prices) / len(prices))
            else:
                raise CannotGetTokenPriceFromApi(
                    "There is no working provider for token=%s" % self.address
                )

    def calculate_payment(self, eth_payment: int) -> int:
        """
        Converts an ether payment to a token payment
        :param eth_payment: Ether payment (in wei)
        :return: Token payment equivalent for the ether value
        """
        return math.ceil(eth_payment / self.get_eth_value())

    def calculate_gas_price(self, gas_price: int, price_margin: float = 1.0) -> int:
        """
        Converts ether gas price to token's gas price
        :param gas_price: Regular ether gas price
        :param price_margin: Threshold to estimate a little higher, so tx will
        not be rejected in a few minutes
        :return:
        """
        return math.ceil(gas_price / self.get_eth_value() * price_margin)

    def get_full_logo_uri(self):
        if urlparse(self.logo_uri).netloc:
            # Absolute uri stored
            return self.logo_uri
        elif self.logo_uri:
            # Just path/filename with extension stored
            return urljoin(settings.TOKEN_LOGO_BASE_URI, self.logo_uri)
        else:
            # Generate logo uri based on configuration
            return urljoin(
                settings.TOKEN_LOGO_BASE_URI,
                self.address + settings.TOKEN_LOGO_EXTENSION,
            )
