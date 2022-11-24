import math
from logging import getLogger
from typing import Iterable, List, Optional

from django.conf import settings
from django.core.cache import cache

import numpy as np
from web3 import Web3
from web3.types import BlockData

from gnosis.eth import EthereumClient, EthereumClientProvider

from .models import GasPrice

logger = getLogger(__name__)


class NoBlocksFound(Exception):
    pass


class GasStationProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            if settings.FIXED_GAS_PRICE is not None:
                cls.instance = GasStationMock(gas_price=settings.FIXED_GAS_PRICE)
            else:
                cls.instance = GasStation(
                    EthereumClientProvider(), settings.GAS_STATION_NUMBER_BLOCKS
                )
                w3 = cls.instance.w3
                if w3.isConnected() and int(w3.net.version) > 314158:  # Ganache
                    logger.warning(
                        "Using mock Gas Station because no `w3.net.version` was detected"
                    )
                    cls.instance = GasStationMock()
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class GasStation:
    def __init__(
        self,
        ethereum_client: EthereumClient,
        number_of_blocks: int = 200,
        cache_timeout_seconds: int = 10 * 60,
        constant_gas_increment: int = 1,
    ):  # Increase a little for fastest mining for API Calls

        self.ethereum_client = ethereum_client
        self.number_of_blocks = number_of_blocks
        self.cache_timeout = cache_timeout_seconds
        self.constant_gas_increment = constant_gas_increment
        self.w3 = self.ethereum_client.w3

    def _get_block_cache_key(self, block_number: int):
        return "block:%d" % block_number

    def _get_block_from_cache(self, block_number: int) -> Optional[BlockData]:
        return cache.get(self._get_block_cache_key(block_number))

    def _store_block_in_cache(self, block_number: int, block: BlockData):
        return cache.set(
            self._get_block_cache_key(block_number), block, self.cache_timeout
        )

    def _get_gas_price_cache_key(self):
        return "gas_price"

    def _get_gas_price_from_cache(self) -> Optional[GasPrice]:
        return cache.get(self._get_gas_price_cache_key())

    def _store_gas_price_in_cache(self, gas_price: GasPrice):
        return cache.set(self._get_gas_price_cache_key(), gas_price)

    def get_tx_gas_prices(self, block_numbers: Iterable[int]) -> List[int]:
        """
        :param block_numbers: Block numbers to retrieve
        :return: Return a list with `gas_price` for every block provided
        """
        cached_blocks = []
        not_cached_block_numbers = []

        for block_number in block_numbers:
            block = self._get_block_from_cache(block_number)
            if block:
                cached_blocks.append(block)
            else:
                not_cached_block_numbers.append(block_number)

        requested_blocks = self.ethereum_client.get_blocks(
            not_cached_block_numbers, full_transactions=True
        )
        for block_number, block in zip(not_cached_block_numbers, requested_blocks):
            if block:
                requested_blocks.append(block)
                self._store_block_in_cache(block["number"], block)
            else:
                logger.warning(
                    "Cannot find block-number=%d, a reorg happened", block_number
                )

        gas_prices = [
            transaction["gasPrice"]
            for block in requested_blocks + cached_blocks
            for transaction in block["transactions"]
            if transaction.get("gasPrice")
        ]

        return gas_prices

    def calculate_gas_prices(self) -> GasPrice:
        current_block_number = self.w3.eth.block_number
        block_numbers = range(
            current_block_number - self.number_of_blocks, current_block_number
        )
        gas_prices = self.get_tx_gas_prices(block_numbers)

        if not gas_prices:
            raise NoBlocksFound
        else:
            np_gas_prices = np.array(gas_prices)
            lowest = np_gas_prices.min() + self.constant_gas_increment
            safe_low = (
                math.ceil(np.percentile(np_gas_prices, 30))
                + self.constant_gas_increment
            )
            standard = (
                math.ceil(np.percentile(np_gas_prices, 50))
                + self.constant_gas_increment
            )
            fast = (
                math.ceil(np.percentile(np_gas_prices, 75))
                + self.constant_gas_increment
            )
            fastest = np_gas_prices.max() + self.constant_gas_increment

            gas_price = GasPrice.objects.create(
                lowest=lowest,
                safe_low=safe_low,
                standard=standard,
                fast=fast,
                fastest=fastest,
            )

            self._store_gas_price_in_cache(gas_price)
            logger.info(
                f"Calculated gas price lowest={lowest} safe_low={safe_low} standard={standard} "
                f"fast={fast} fastest={fastest}"
            )
            return gas_price

    def get_gas_prices(self) -> GasPrice:
        gas_price = self._get_gas_price_from_cache()
        if not gas_price:
            try:
                gas_price = GasPrice.objects.latest()
            except GasPrice.DoesNotExist:
                # This should never happen, just the first execution
                # Celery worker should have GasPrice created
                gas_price = self.calculate_gas_prices()
        return gas_price


class GasStationMock(GasStation):
    def __init__(self, gas_price: Optional[int] = None):
        if gas_price is None:
            self.lowest = Web3.toWei(1, "gwei")
            self.safe_low = Web3.toWei(5, "gwei")
            self.standard = Web3.toWei(10, "gwei")
            self.fast = Web3.toWei(20, "gwei")
            self.fastest = Web3.toWei(50, "gwei")
        else:
            # Set all gas prices to the same (for running on xDai)
            self.lowest = Web3.toWei(gas_price, "gwei")
            self.safe_low = Web3.toWei(gas_price, "gwei")
            self.standard = Web3.toWei(gas_price, "gwei")
            self.fast = Web3.toWei(gas_price, "gwei")
            self.fastest = Web3.toWei(gas_price, "gwei")

    def calculate_gas_prices(self) -> GasPrice:
        return GasPrice(
            lowest=self.lowest,
            safe_low=self.safe_low,
            standard=self.standard,
            fast=self.fast,
            fastest=self.fastest,
        )

    def get_gas_prices(self) -> GasPrice:
        return self.calculate_gas_prices()
