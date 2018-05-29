import math
from typing import Dict, Iterable

import numpy as np
import requests
from django.core.cache import cache
from web3 import HTTPProvider, Web3
from web3.middleware import geth_poa_middleware

from .models import GasPrice


class GasStation:
    def __init__(self,
                 http_provider_uri='http://localhost:8545',
                 number_of_blocks: int=200,
                 cache_timeout_seconds=10 * 60):
        self.http_provider_uri = http_provider_uri
        self.http_session = requests.session()
        self.w3 = Web3(HTTPProvider(http_provider_uri))
        self.w3.middleware_stack.inject(geth_poa_middleware, layer=0)
        self.number_of_blocks = number_of_blocks
        self.cache_timeout = cache_timeout_seconds

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
                "id": 1
                }

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

        requested_blocks = [rpc_response['result'] for rpc_response in self._do_request(rpc_request)]

        gas_prices = []

        for block in requested_blocks + cached_blocks:
            block_number = int(block['number'], 16)
            self._store_block_in_cache(block_number, block)

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

        np_gas_prices = np.array(gas_prices)

        lowest = np_gas_prices.min()
        safe_low = math.ceil(np.percentile(np_gas_prices, 30))
        standard = math.ceil(np.percentile(np_gas_prices, 50))
        fast = math.ceil(np.percentile(np_gas_prices, 75))
        fastest = np_gas_prices.max()

        gas_price = GasPrice(lowest=lowest,
                             safe_low=safe_low,
                             standard=standard,
                             fast=fast,
                             fastest=fastest)

        gas_price.save()
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
