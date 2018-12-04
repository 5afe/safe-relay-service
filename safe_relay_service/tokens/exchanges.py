import logging
import requests
from abc import ABC, abstractmethod


logger = logging.getLogger(__name__)


class CannotGetTokenPriceFromApi(Exception):
    pass


class PriceOracle(ABC):
    @abstractmethod
    def get_price(self, ticker) -> float:
        pass


class Kraken:
    def get_price(self, ticker) -> float:
        url = 'https://api.kraken.com/0/public/Ticker?pair=' + ticker
        response = requests.get(url)
        api_json = response.json()
        error = api_json.get('error')
        if not response.ok or error:
            logger.warning('Cannot get price from url=%s' % url)
            raise CannotGetTokenPriceFromApi(str(api_json['error']))
        price = float(api_json['result'][ticker]['c'][0])
        return price


class DutchX:
    def get_price(self, ticker) -> float:
        url = 'https://dutchx.d.exchange/api/v1/markets/{}/price'.format(ticker)
        response = requests.get(url)
        api_json = response.json()
        if not response.ok or api_json is None:
            logger.warning('Cannot get price from url=%s' % url)
            raise CannotGetTokenPriceFromApi(api_json)
        return float(api_json)



def get_price_oracle(name) -> PriceOracle:
    if name.lower() == 'kraken':
        return Kraken
    else:
        return NotImplementedError


