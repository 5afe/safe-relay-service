import math
from logging import getLogger
from typing import Dict, Iterable, Union

from django.conf import settings
from django.core.cache import cache

import numpy as np
import requests
from web3 import HTTPProvider, Web3
from web3.middleware import geth_poa_middleware

from .models import GasPrice

logger = getLogger(__name__)


class NoBlocksFound(Exception):
    pass


class GasStationProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = GasStation(settings.ETHEREUM_NODE_URL, settings.GAS_STATION_NUMBER_BLOCKS)
            w3 = cls.instance.w3
            if w3.isConnected() and int(w3.net.version) > 1000:  # Ganache
                logger.warning('Using mock Gas Station because no chainId was detected')
                cls.instance = GasStationMock()
            elif settings.SAFE_GAS_PRICE is not None:
                cls.instance = GasStationMock(gas_price=settings.SAFE_GAS_PRICE)
        return cls.instance


class GasStation:
    CONSTANT_GAS_INCREMENT = 1  # Increase a little for fastest mining for API Calls

    def __init__(self,
                 http_provider_uri='http://localhost:8545',
                 number_of_blocks: int=200,
                 cache_timeout_seconds=10 * 60):
        self.http_provider_uri = http_provider_uri
        self.http_session = requests.session()
        self.number_of_blocks = number_of_blocks
        self.cache_timeout = cache_timeout_seconds
        self.w3 = Web3(HTTPProvider(http_provider_uri))
        try:
            if self.w3.net.chainId != 1:
                self.w3.middleware_stack.inject(geth_poa_middleware, layer=0)
            # For tests using dummy connections (like IPC)
        except (ConnectionError, FileNotFoundError):
            self.w3.middleware_stack.inject(geth_poa_middleware, layer=0)

    def _get_block_cache_key(self, block_number):
        return 'block:%d' % block_number

    def _get_block_from_cache(self, block_number):
        return cache.get(self._get_block_cache_key(block_number))

    def _store_block_in_cache(self, block_number, block):
        return cache.set(self._get_block_cache_key(block_number), block, self.cache_timeout)

    def _get_gas_price_cache_key(self):
        return 'gas_price'

    def _get_gas_price_from_cache(self):
        return cache.get(self._get_gas_price_cache_key())

    def _store_gas_price_in_cache(self, gas_price):
        return cache.set(self._get_gas_price_cache_key(), gas_price)

    def _build_block_request(self, block_number: int, full_transactions: bool=False) -> Dict[str, any]:
        block_number_hex = '0x{:x}'.format(block_number)
        return {"jsonrpc": "2.0",
                "method": "eth_getBlockByNumber",
                "params": [block_number_hex, full_transactions],
                "id": block_number}

    def _do_request(self, rpc_request):
        return self.http_session.post(self.http_provider_uri, json=rpc_request).json()

    def get_tx_gas_prices(self, block_numbers: Iterable[int]):
        cached_blocks = []
        not_cached_block_numbers = []

        for block_number in block_numbers:
            block = self._get_block_from_cache(block_number)
            if block:
                cached_blocks.append(block)
            else:
                not_cached_block_numbers.append(block_number)

        rpc_request = [self._build_block_request(block_number, full_transactions=True)
                       for block_number in not_cached_block_numbers]

        requested_blocks = []
        for rpc_response in self._do_request(rpc_request):
            block = rpc_response['result']
            if block:
                requested_blocks.append(block)
                block_number = int(block['number'], 16)
                self._store_block_in_cache(block_number, block)
            else:
                block_number = rpc_response['id']
                logger.warning('Cannot find block-number=%d, a reorg happened', block_number)

        gas_prices = []
        for block in requested_blocks + cached_blocks:
            for transaction in block['transactions']:
                gas_price = int(transaction['gasPrice'], 16)
                # Don't include miner transactions (0 gasPrice)
                if gas_price:
                    gas_prices.append(gas_price)

        return gas_prices

    def calculate_gas_prices(self) -> GasPrice:
        current_block_number = self.w3.eth.blockNumber
        block_numbers = range(current_block_number - self.number_of_blocks, current_block_number)
        gas_prices = self.get_tx_gas_prices(block_numbers)

        if not gas_prices:
            raise NoBlocksFound
        else:
            np_gas_prices = np.array(gas_prices)
            lowest = np_gas_prices.min() + self.CONSTANT_GAS_INCREMENT
            safe_low = math.ceil(np.percentile(np_gas_prices, 30)) + self.CONSTANT_GAS_INCREMENT
            standard = math.ceil(np.percentile(np_gas_prices, 50)) + self.CONSTANT_GAS_INCREMENT
            fast = math.ceil(np.percentile(np_gas_prices, 75)) + self.CONSTANT_GAS_INCREMENT
            fastest = np_gas_prices.max() + self.CONSTANT_GAS_INCREMENT

            gas_price = GasPrice.objects.create(lowest=lowest,
                                                safe_low=safe_low,
                                                standard=standard,
                                                fast=fast,
                                                fastest=fastest)

            self._store_gas_price_in_cache(gas_price)
            return gas_price

    def get_gas_prices(self) -> GasPrice:
        gas_price = self._get_gas_price_from_cache()
        if not gas_price:
            try:
                gas_price = GasPrice.objects.earliest()
            except GasPrice.DoesNotExist:
                # This should never happen, just the first execution
                # Celery worker should have GasPrice created
                gas_price = self.calculate_gas_prices()

        return gas_price


class GasStationMock(GasStation):
    def __init__(self, gas_price: Union[None, int]=None):
        if gas_price is None:
            self.lowest = 1
            self.safe_low = 5
            self.standard = 10
            self.fast = 20
            self.fastest = 50
        else:
            self.lowest = gas_price
            self.safe_low = gas_price
            self.standard = gas_price
            self.fast = gas_price
            self.fastest = gas_price

    def calculate_gas_prices(self) -> GasPrice:
        return GasPrice(lowest=self.lowest,
                        safe_low=self.safe_low,
                        standard=self.standard,
                        fast=self.fast,
                        fastest=self.fastest)
