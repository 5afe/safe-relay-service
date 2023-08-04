from abc import ABC, abstractmethod
from logging import getLogger
from typing import Any, List, Optional, Set, Tuple

from django.db.models import Min

from web3 import Web3

from gnosis.eth import EthereumClient

from ..models import (
    EthereumBlock,
    EthereumTx,
    SafeContract,
    SafeCreation,
    SafeCreation2,
    SafeTxStatus,
)
from ..utils import chunks

logger = getLogger(__name__)


class TransactionScanService(ABC):
    def __init__(
        self,
        ethereum_client: EthereumClient,
        confirmations: int = 10,
        block_process_limit: int = 10000,
        updated_blocks_behind: int = 100,
        query_chunk_size: int = 500,
        safe_creation_threshold: int = 150000,
    ):
        """
        :param ethereum_client:
        :param confirmations: Threshold of blocks to scan to prevent reorgs
        :param block_process_limit: Number of blocks to scan at a time for relevant data. `0` == `No limit`
        :param updated_blocks_behind: Number of blocks scanned that a safe can be behind and still be considered
        as almost updated. For example, if `updated_blocks_behind` is 100, `current block number` is 200, and last
        scan for a safe was stopped on block 150, safe is almost updated (200 - 100 < 150)
        :param query_chunk_size: Number of addresses to query for relevant data in the same request. By testing,
        it seems that `100` can be a good value
        :param safe_creation_threshold: For old safes, creation `block_number` was not stored, so we set a little
        threshold to get the funding tx of the safe. That threshold is `150000 blocks = 1 week` by default
        """
        self.ethereum_client = ethereum_client
        self.confirmations = confirmations
        self.block_process_limit = block_process_limit
        self.updated_blocks_behind = updated_blocks_behind
        self.query_chunk_size = query_chunk_size
        self.safe_creation_threshold = safe_creation_threshold

    @property
    @abstractmethod
    def database_field(self):
        """
        Database field on `SafeTxStatus` to store scan status
        :return:
        """
        pass

    @abstractmethod
    def find_relevant_tx_hashes(
        self, safe_addresses: List[str], from_block_number: int, to_block_number: int
    ) -> Set[str]:
        """
        Find blockchain relevant tx hashes for the `safe_addresses`
        :param safe_addresses:
        :param from_block_number
        :param to_block_number
        :return: Set of relevant tx hashes
        """
        pass

    @abstractmethod
    def process_tx_hash(self, tx_hash: str) -> List[Any]:
        """
        Process provided `tx_hash` to retrieve relevant data (internal txs, events...)
        :param tx_hash:
        :return:
        """
        pass

    def create_or_update_ethereum_tx(self, tx_hash: str) -> EthereumTx:
        try:
            ethereum_tx = EthereumTx.objects.get(tx_hash=tx_hash)
            if ethereum_tx.block is None:
                tx_receipt = self.ethereum_client.get_transaction_receipt(tx_hash)
                ethereum_tx.block = self.get_or_create_ethereum_block(
                    tx_receipt.blockNumber
                )
                ethereum_tx.gas_used = tx_receipt.gasUsed
                ethereum_tx.save()
            return ethereum_tx
        except EthereumTx.DoesNotExist:
            tx_receipt = self.ethereum_client.get_transaction_receipt(tx_hash)
            ethereum_block = self.get_or_create_ethereum_block(tx_receipt.blockNumber)
            tx = self.ethereum_client.get_transaction(tx_hash)
            return EthereumTx.objects.create_from_tx_dict(
                tx, tx_hash, tx_receipt=tx_receipt, ethereum_block=ethereum_block
            )

    def get_or_create_ethereum_block(self, block_number: int):
        try:
            return EthereumBlock.objects.get(number=block_number)
        except EthereumBlock.DoesNotExist:
            block = self.ethereum_client.get_block(block_number)
            return EthereumBlock.objects.create_from_block(block)

    def get_or_create_safe_tx_status(self, safe_address: str) -> SafeTxStatus:
        safe_contract = SafeContract.objects.get(address=safe_address)
        try:
            return SafeTxStatus.objects.get(safe=safe_contract)
        except SafeTxStatus.DoesNotExist:
            # We subtract a little (about one week) to get the funding tx of the safe
            # On new Safes this object is created when SafeCreation2 is created and is more accurate
            block_number = max(
                0,
                self.get_safe_creation_block_number(safe_address)
                - self.safe_creation_threshold,
            )
            logger.info(
                "Safe=%s - Creating SafeTxStatus at block=%d",
                safe_address,
                block_number,
            )
            return SafeTxStatus.objects.create(
                safe=safe_contract,
                initial_block_number=block_number,
                tx_block_number=block_number,
                erc_20_block_number=block_number,
            )

    def get_safe_creation_block_number(self, safe_address: str) -> int:
        """
        :param safe_address:
        :return: Block number when a safe was deployed
        """
        try:
            safe_creation_2 = SafeCreation2.objects.get(safe__address=safe_address)
            if safe_creation_2.block_number:
                return safe_creation_2.block_number
            else:
                # This should never happen, every deployed safe will have `block_number` stored
                logger.warning("Safe=%s has not a `block_number` stored")
                return self.ethereum_client.get_transaction_receipt(
                    safe_creation_2.tx_hash
                ).blockNumber
        except SafeCreation2.DoesNotExist:
            try:
                safe_creation = SafeCreation.objects.get(safe__address=safe_address)
                tx_receipt = self.ethereum_client.get_transaction_receipt(
                    safe_creation.tx_hash
                )
                if tx_receipt:
                    return tx_receipt.blockNumber
                else:
                    logger.warning(
                        "Safe=%s with tx-hash=%s not valid",
                        safe_address,
                        safe_creation.tx_hash,
                    )
                    return 0
            except SafeCreation.DoesNotExist:
                return 0

    def get_almost_updated_safes(self, current_block_number: int) -> List[SafeTxStatus]:
        """
        For safes almost updated (< `updated_blocks_behind` blocks) we process them together
        (`query_chunk_size` safes at the same time)
        :param current_block_number:
        :return:
        """
        return SafeTxStatus.objects.deployed().filter(
            **{
                self.database_field + "__lt": current_block_number - self.confirmations,
                self.database_field
                + "__gt": current_block_number
                - self.updated_blocks_behind,
            }
        )

    def get_not_updated_safes(self, current_block_number: int) -> List[SafeTxStatus]:
        """
        For safes not updated (> `updated_blocks_behind` blocks) we process them one by one (node hangs)
        :param current_block_number:
        :return:
        """
        return SafeTxStatus.objects.deployed().filter(
            **{self.database_field + "__lt": current_block_number - self.confirmations}
        )

    def update_safe_tx_status(
        self, safe_addresses: List[str], to_block_number: int
    ) -> int:
        return SafeTxStatus.objects.filter(safe_id__in=safe_addresses).update(
            **{self.database_field: to_block_number}
        )

    def get_block_numbers_for_search(
        self, safe_addresses: List[str]
    ) -> Optional[Tuple[int, int]]:
        """
        :param safe_addresses:
        :return: Minimum common `from_block_number` and `to_block_number` for search of relevant `tx hashes`
        """
        block_process_limit = self.block_process_limit
        confirmations = self.confirmations
        current_block_number = self.ethereum_client.current_block_number

        safe_tx_status_queryset = SafeTxStatus.objects.filter(
            safe_id__in=safe_addresses
        )
        common_minimum_block_number = safe_tx_status_queryset.aggregate(
            **{self.database_field: Min(self.database_field)}
        )[self.database_field]
        if common_minimum_block_number is None:  # Empty queryset
            return

        from_block_number = common_minimum_block_number + 1
        if (current_block_number - common_minimum_block_number) < confirmations:
            return  # We don't want problems with reorgs

        if block_process_limit:
            to_block_number = min(
                common_minimum_block_number + block_process_limit,
                current_block_number - confirmations,
            )
        else:
            to_block_number = current_block_number - confirmations

        return from_block_number, to_block_number

    def process_addresses(
        self, safe_addresses: List[str]
    ) -> Optional[Tuple[List[Any], bool]]:
        """
        Find and process relevant data for `safe_addresses`, then store and return it
        :param safe_addresses: Addresses to process
        :return: List of processed data and a boolean (`True` if no more blocks to scan, `False` otherwise)
        """
        assert safe_addresses, "Safe addresses cannot be empty!"
        assert all(
            [Web3.is_checksum_address(safe_address) for safe_address in safe_addresses]
        ), ("A safe address has invalid checksum: %s" % safe_addresses)

        parameters = self.get_block_numbers_for_search(safe_addresses)
        if parameters is None:
            return
        from_block_number, to_block_number = parameters
        updated = to_block_number == (
            self.ethereum_client.current_block_number - self.confirmations
        )
        tx_hashes = self.find_relevant_tx_hashes(
            safe_addresses, from_block_number, to_block_number
        )
        processed_objects = [self.process_tx_hash(tx_hash) for tx_hash in tx_hashes]
        flatten_processed_objects = [
            item for sublist in processed_objects for item in sublist
        ]

        self.update_safe_tx_status(safe_addresses, to_block_number)
        return flatten_processed_objects, updated

    def process_all(self):
        """
        Find and process relevant data for existing safes
        :return: Number of safes processed
        """
        current_block_number = self.ethereum_client.current_block_number
        number_safes = 0

        # We need to cast the `iterable` to `list`, if not chunks will not work well when models are updated
        almost_updated_safe_tx_statuses = list(
            self.get_almost_updated_safes(current_block_number)
        )
        almost_updated_safe_tx_statuses_chunks = chunks(
            almost_updated_safe_tx_statuses, self.query_chunk_size
        )
        for almost_updated_addresses_chunk in almost_updated_safe_tx_statuses_chunks:
            almost_updated_addresses = [
                safe_tx_status.safe_id
                for safe_tx_status in almost_updated_addresses_chunk
            ]
            self.process_addresses(almost_updated_addresses)
            number_safes += len(almost_updated_addresses)

        for safe_tx_status in self.get_not_updated_safes(current_block_number):
            updated = False
            while not updated:
                _, updated = self.process_addresses([safe_tx_status.safe_id])
            number_safes += 1
        return number_safes
