from logging import getLogger
from typing import List, Set

from gnosis.eth import EthereumClient

from ..models import EthereumEvent
from .transaction_scan_service import TransactionScanService

logger = getLogger(__name__)


class Erc20EventsServiceProvider:
    def __new__(cls):
        if not hasattr(cls, "instance"):
            from django.conf import settings

            cls.instance = Erc20EventsService(
                EthereumClient(settings.ETHEREUM_NODE_URL)
            )
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class Erc20EventsService(TransactionScanService):
    """
    Indexes ERC20 and ERC721 `Transfer` Event (as ERC721 has the same topic)
    """

    def __init__(
        self,
        ethereum_client: EthereumClient,
        block_process_limit: int = 10000,
        updated_blocks_behind: int = 200,
        query_chunk_size: int = 500,
        **kwargs
    ):
        super().__init__(
            ethereum_client,
            block_process_limit=block_process_limit,
            updated_blocks_behind=updated_blocks_behind,
            query_chunk_size=query_chunk_size,
            **kwargs
        )

    @property
    def database_field(self):
        return "erc_20_block_number"

    def find_relevant_tx_hashes(
        self, safe_addresses: List[str], from_block_number: int, to_block_number: int
    ) -> Set[str]:
        """
        Search for tx hashes with erc20 transfer events (`from` and `to`) of a `safe_address`
        :param safe_addresses:
        :param from_block_number: Starting block number
        :param to_block_number: Ending block number
        :return: Tx hashes of txs with relevant erc20 transfer events for the `safe_addresses`
        """
        logger.debug(
            "Searching for erc20 txs from block-number=%d to block-number=%d - Safes=%s",
            from_block_number,
            to_block_number,
            safe_addresses,
        )

        # It will get erc721 events, as `topic` is the same
        erc20_transfer_events = self.ethereum_client.erc20.get_total_transfer_history(
            safe_addresses, from_block=from_block_number, to_block=to_block_number
        )
        # Log INFO if erc events found, DEBUG otherwise
        logger_fn = logger.info if erc20_transfer_events else logger.debug
        logger_fn(
            "Found %d relevant erc20 txs between block-number=%d and block-number=%d. Safes=%s",
            len(erc20_transfer_events),
            from_block_number,
            to_block_number,
            safe_addresses,
        )

        return set([event["transactionHash"] for event in erc20_transfer_events])

    def process_tx_hash(self, tx_hash: str) -> List[EthereumEvent]:
        """
        Search on Ethereum and store erc20 transfer events for provided `tx_hash`
        :param tx_hash:
        :return: List of `Erc20TransferEvent` already stored in database
        """
        ethereum_tx = self.create_or_update_ethereum_tx(tx_hash)
        tx_receipt = self.ethereum_client.get_transaction_receipt(tx_hash)
        decoded_logs = self.ethereum_client.erc20.decode_logs(tx_receipt.logs)
        return [
            EthereumEvent.objects.get_or_create_erc20_or_721_event(event)
            for event in decoded_logs
        ]
