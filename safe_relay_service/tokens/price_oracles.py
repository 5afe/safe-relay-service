import logging
from abc import ABC, abstractmethod
from typing import Any, Dict

import requests
from cachetools import TTLCache, cached

from gnosis.eth import EthereumClientProvider
from gnosis.eth.oracles import KyberOracle, OracleException, UniswapOracle

logger = logging.getLogger(__name__)


class ExchangeApiException(Exception):
    pass


class CannotGetTokenPriceFromApi(ExchangeApiException):
    pass


class InvalidTicker(ExchangeApiException):
    pass


class PriceOracle(ABC):
    @abstractmethod
    def get_price(self, ticker) -> float:
        pass


class Binance(PriceOracle):
    """
    Get valid symbols from https://api.binance.com/api/v1/exchangeInfo
    Remember to always use USDT instead of USD
    """

    @cached(cache=TTLCache(maxsize=1024, ttl=60))
    def get_price(self, ticker) -> float:
        url = "https://api.binance.com/api/v3/avgPrice?symbol=" + ticker
        response = requests.get(url)
        api_json = response.json()
        if not response.ok:
            logger.warning("Cannot get price from url=%s", url)
            raise CannotGetTokenPriceFromApi(api_json.get("msg"))
        return float(api_json["price"])


class DutchX(PriceOracle):
    def validate_ticker(self, ticker: str):
        # Example ticker `0x89d24A6b4CcB1B6fAA2625fE562bDD9a23260359-WETH`
        if "WETH" not in ticker:
            raise InvalidTicker(ticker)

    def reverse_ticker(self, ticker: str):
        return "-".join(reversed(ticker.split("-")))

    @cached(cache=TTLCache(maxsize=1024, ttl=1200))
    def get_price(self, ticker: str) -> float:
        self.validate_ticker(ticker)
        url = (
            "https://dutchx.d.exchange/api/v1/markets/{}/prices/custom-median?requireWhitelisted=false&"
            "maximumTimePeriod=388800&numberOfAuctions=9".format(ticker)
        )
        response = requests.get(url)
        api_json = response.json()
        if not response.ok or api_json is None:
            logger.warning("Cannot get price from url=%s", url)
            raise CannotGetTokenPriceFromApi(api_json)
        return float(api_json)


class Huobi(PriceOracle):
    """
    Get valid symbols from https://api.huobi.pro/v1/common/symbols
    """

    @cached(cache=TTLCache(maxsize=1024, ttl=60))
    def get_price(self, ticker) -> float:
        url = "https://api.huobi.pro/market/detail/merged?symbol=%s" % ticker
        response = requests.get(url)
        api_json = response.json()
        error = api_json.get("err-msg")
        if not response.ok or error:
            logger.warning("Cannot get price from url=%s", url)
            raise CannotGetTokenPriceFromApi(error)
        return float(api_json["tick"]["close"])


class Kraken(PriceOracle):
    @cached(cache=TTLCache(maxsize=1024, ttl=60))
    def get_price(self, ticker) -> float:
        url = "https://api.kraken.com/0/public/Ticker?pair=" + ticker
        response = requests.get(url)
        api_json = response.json()
        error = api_json.get("error")
        if not response.ok or error:
            logger.warning("Cannot get price from url=%s", url)
            raise CannotGetTokenPriceFromApi(str(api_json["error"]))

        result = api_json["result"]
        for new_ticker in result:
            return float(result[new_ticker]["c"][0])


class Uniswap(PriceOracle):
    def __init__(self, uniswap_exchange_address: str, **kwargs):
        self.uniswap_exchange_address = uniswap_exchange_address

    @cached(cache=TTLCache(maxsize=1024, ttl=60))
    def get_price(self, ticker: str) -> float:
        """
        :param ticker: Address of the token
        :return: price
        """
        ethereum_client = EthereumClientProvider()
        uniswap = UniswapOracle(ethereum_client, self.uniswap_exchange_address)
        try:
            return uniswap.get_price(ticker)
        except OracleException as e:
            raise CannotGetTokenPriceFromApi from e


class Kyber(PriceOracle):
    def __init__(self, kyber_network_proxy_address: str, **kwargs):
        self.kyber_network_proxy_address = kyber_network_proxy_address

    @cached(cache=TTLCache(maxsize=1024, ttl=60))
    def get_price(self, ticker: str) -> float:
        """
        :param ticker: Address of the token
        :return: price
        """
        ethereum_client = EthereumClientProvider()
        kyber = KyberOracle(ethereum_client, self.kyber_network_proxy_address)
        try:
            return kyber.get_price(ticker)
        except OracleException as e:
            raise CannotGetTokenPriceFromApi from e


def get_price_oracle(name: str, configuration: Dict[Any, Any] = {}) -> PriceOracle:
    oracles = {
        "binance": Binance,
        "dutchx": DutchX,
        "huobi": Huobi,
        "kraken": Kraken,
        "kyber": Kyber,
        "uniswap": Uniswap,
    }

    oracle = oracles.get(name.lower())
    if oracle:
        return oracle(**configuration)
    else:
        raise NotImplementedError("Oracle '%s' not found" % name)
