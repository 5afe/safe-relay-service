import logging
from abc import ABC, abstractmethod

import requests

logger = logging.getLogger(__name__)


class CannotGetTokenPriceFromApi(Exception):
    pass


class PriceOracle(ABC):
    @abstractmethod
    def get_price(self, ticker) -> float:
        pass


class Binance:
    def get_price(self, ticker) -> float:
        # Remember to use always USDT instead of USD
        url = 'https://api.binance.com/api/v3/avgPrice?symbol=' + ticker
        response = requests.get(url)
        api_json = response.json()
        if not response.ok:
            logger.warning('Cannot get price from url=%s' % url)
            raise CannotGetTokenPriceFromApi(api_json.get('msg'))
        return float(api_json['price'])


class DutchX:
    def replace_tokens(self, ticker):
        symbols = []
        for symbol in ticker.split('-'):
            symbol_lower = symbol.lower()
            if symbol_lower == 'dai':
                symbol = '0x89d24A6b4CcB1B6fAA2625fE562bDD9a23260359'
            symbols.append(symbol)
        return '-'.join(symbols)

    def get_price(self, ticker) -> float:
        ticker = self.replace_tokens(ticker)
        url = 'https://dutchx.d.exchange/api/v1/markets/{}/price'.format(ticker)
        response = requests.get(url)
        api_json = response.json()
        if not response.ok or api_json is None:
            logger.warning('Cannot get price from url=%s' % url)
            raise CannotGetTokenPriceFromApi(api_json)
        return float(api_json)


class Huobi:
    """
    Get valid symbols from https://api.huobi.pro/v1/common/symbols
    """
    def get_price(self, ticker) -> float:
        url = 'https://api.huobi.pro/market/detail/merged?symbol=%s' % ticker
        response = requests.get(url)
        api_json = response.json()
        error = api_json.get('err-msg')
        if not response.ok or error:
            logger.warning('Cannot get price from url=%s' % url)
            raise CannotGetTokenPriceFromApi(error)
        return float(api_json['tick']['close'])


class Kraken:
    def get_price(self, ticker) -> float:
        url = 'https://api.kraken.com/0/public/Ticker?pair=' + ticker
        response = requests.get(url)
        api_json = response.json()
        error = api_json.get('error')
        if not response.ok or error:
            logger.warning('Cannot get price from url=%s' % url)
            raise CannotGetTokenPriceFromApi(str(api_json['error']))

        result = api_json['result']
        for new_ticker in result:
            return float(result[new_ticker]['c'][0])


def get_price_oracle(name) -> PriceOracle:
    name = name.lower()
    if name == 'binance':
        return Binance()
    elif name == 'dutchx':
        return DutchX()
    elif name == 'huobi':
        return Huobi()
    elif name == 'kraken':
        return Kraken()
    else:
        raise NotImplementedError
