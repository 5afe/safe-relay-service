from logging import getLogger
from typing import Dict, List, Optional, Tuple

from django.db.models import Min

from hexbytes import HexBytes
from web3 import Web3

from gnosis.eth import EthereumClient

from ..models import (EthereumTx, EthereumTxCallType, InternalTx, SafeContract,
                      SafeCreation, SafeCreation2, SafeTxStatus)
from ..utils import chunks

logger = getLogger(__name__)


class InternalTxServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            cls.instance = InternalTxService(EthereumClient(settings.ETHEREUM_TRACING_NODE_URL))
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class InternalTxService:
    def __init__(self, ethereum_client: EthereumClient, confirmations: int = 10,
                 updated_blocks_behind: int = 100, query_chunk_size: int = 100,
                 safe_creation_threshold: int = 150000):
        """
        :param ethereum_client:
        :param confirmations: Margin of blocks to scan to prevent reorgs
        :param updated_blocks_behind: Number of blocks scanned that a safe can be behind and still be considered
        as almost updated. For example, if `updated_blocks_behind` is 100, `current block number` is 200, and last
        scan for a safe was stopped on block 150, safe is almost updated (200 - 100 < 150)
        :param query_chunk_size: Number of addresses to query for internal txs in the same query. By testing, it seems
        that `100` can be a good value
        :param safe_creation_threshold: For old safes, creation `block_number` was not stored, so we set a little
        threshold to get the funding tx of the safe. That threshold is `150000 blocks = 1 week` by default
        """
        self.ethereum_client = ethereum_client
        self.confirmations = confirmations
        self.updated_blocks_behind = updated_blocks_behind
        self.query_chunk_size = query_chunk_size
        self.safe_creation_threshold = safe_creation_threshold

    def get_or_create_ethereum_tx(self, tx_hash: str) -> EthereumTx:
        try:
            return EthereumTx.objects.get(tx_hash=tx_hash)
        except EthereumTx.DoesNotExist:
            tx_receipt = self.ethereum_client.get_transaction_receipt(tx_hash)
            tx = self.ethereum_client.get_transaction(tx_hash)
            return EthereumTx.objects.create(
                tx_hash=tx_hash,
                block_number=tx_receipt.blockNumber,
                gas_used=tx_receipt.gasUsed,
                _from=tx['from'],
                gas=tx['gas'],
                gas_price=tx['gasPrice'],
                data=HexBytes(tx['input']),
                nonce=tx['nonce'],
                to=tx['to'],
                value=tx['value'],
            )

    def get_or_create_safe_tx_status(self, safe_address: str) -> SafeTxStatus:
        safe_contract = SafeContract.objects.get(address=safe_address)
        try:
            return SafeTxStatus.objects.get(safe=safe_contract)
        except SafeTxStatus.DoesNotExist:
            # We subtract a little (about one week) to get the funding tx of the safe
            # On new Safes this object is created when SafeCreation2 is created and is more accurate
            block_number = max(0, self.get_safe_creation_block_number(safe_address) - self.safe_creation_threshold)
            logger.info('Safe=%s - Creating SafeTxStatus at block=%d', safe_address, block_number)
            return SafeTxStatus.objects.create(safe=safe_contract,
                                               initial_block_number=block_number,
                                               tx_block_number=block_number,
                                               erc_20_block_number=block_number)

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
                logger.warning('Safe=%s has not a `block_number` stored')
                return self.ethereum_client.get_transaction_receipt(safe_creation_2.tx_hash).blockNumber
        except SafeCreation2.DoesNotExist:
            try:
                safe_creation = SafeCreation.objects.get(safe__address=safe_address)
                tx_receipt = self.ethereum_client.get_transaction_receipt(safe_creation.tx_hash)
                if tx_receipt:
                    return tx_receipt.blockNumber
                else:
                    logger.warning('Safe=%s with tx-hash=%s not valid', safe_address, safe_creation.tx_hash)
                    return 0
            except SafeCreation.DoesNotExist:
                return 0

    def process_all_internal_txs(self):
        """
        Find and process internal txs for existing safes
        :return: Number of safes processed
        """
        current_block_number = self.ethereum_client.current_block_number
        number_safes = 0

        # For safes almost updated (< `updated_blocks_behind` blocks) we process them together
        # (`query_chunk_size` safes at the same time)
        safe_addresses = [safe_tx_status.safe_id for safe_tx_status in SafeTxStatus.objects.deployed().filter(
            tx_block_number__lt=current_block_number - self.confirmations,
            tx_block_number__gt=current_block_number - self.updated_blocks_behind
        )]
        safe_addresses_chunks = chunks(safe_addresses, self.query_chunk_size)
        for safe_addresses_chunk in safe_addresses_chunks:
            number_safes += len(safe_addresses_chunk)
            self.process_internal_txs(safe_addresses_chunk)

        # For safes not updated (> `updated_blocks_behind` blocks) we process them one by one (node hangs)
        for safe_contract in SafeTxStatus.objects.deployed().filter(tx_block_number__lt=current_block_number -
                                                                                        self.confirmations):
            number_safes += 1
            updated = False
            while not updated:
                _, updated = self.process_internal_txs([safe_contract.safe_id])
        return number_safes

    def process_internal_txs(self, safe_addresses: List[str],
                             blocks_process_limit: int = 200000) -> Optional[Tuple[List[InternalTx], bool]]:
        """
        Process internal txs (in and out) of a `safe_address` and store them
        :param safe_addresses: Addresses to process
        :param blocks_process_limit: Number of blocks to process. 0 = All
        :return: List of internal txs processed and a boolean (`True` if no more blocks to scan, `False` otherwise)
        """
        assert safe_addresses, 'Safe addresses cannot be empty!'
        assert all([Web3.isChecksumAddress(safe_address) for safe_address in safe_addresses]), \
            'A safe address has invalid checksum: %s' % safe_addresses

        confirmations = self.confirmations
        current_block_number = self.ethereum_client.current_block_number

        safe_tx_status_queryset = SafeTxStatus.objects.filter(safe_id__in=safe_addresses)
        common_minimum_block_number = safe_tx_status_queryset.aggregate(
            min_tx_block_number=Min('tx_block_number')
        )['min_tx_block_number']
        if common_minimum_block_number is None:  # Empty queryset
            return

        from_block_number = common_minimum_block_number + 1
        if (current_block_number - common_minimum_block_number) < confirmations:
            return  # We don't want problems with reorgs

        if blocks_process_limit:
            to_block_number = min(common_minimum_block_number + blocks_process_limit,
                                  current_block_number - confirmations)
        else:
            to_block_number = current_block_number - confirmations

        logger.info('Searching for internal txs from block-number=%d to block-number=%d - Safes=%s',
                    from_block_number, to_block_number, safe_addresses)

        to_txs = self._process_traces(self.ethereum_client.parity.trace_filter(from_block=from_block_number,
                                                                               to_block=to_block_number,
                                                                               to_address=safe_addresses))

        from_txs = self._process_traces(self.ethereum_client.parity.trace_filter(from_block=from_block_number,
                                                                                 to_block=to_block_number,
                                                                                 from_address=safe_addresses))

        to_and_from_txs = to_txs + from_txs
        updated = to_block_number == (current_block_number - confirmations)
        logger.info('Found %d txs between block-number=%d and block-number%d. Updated=%s - Safes=%s',
                    len(to_and_from_txs), from_block_number, to_block_number, updated, safe_addresses)

        safe_tx_status_queryset.update(tx_block_number=to_block_number)
        return to_and_from_txs, updated

    def _process_traces(self, traces: Dict[str, any]) -> List[InternalTx]:
        internal_txs = []
        for trace in traces:
            ethereum_tx = self.get_or_create_ethereum_tx(trace['transactionHash'])
            call_type = EthereumTxCallType.parse_call_type(trace['action'].get('callType'))
            internal_tx, _ = InternalTx.objects.get_or_create(
                ethereum_tx=ethereum_tx,
                transaction_index=trace['transactionPosition'],
                defaults={
                    '_from': trace['action']['from'],
                    'gas': trace['action']['gas'],
                    'data': trace['action'].get('input') or trace['action'].get('init'),
                    'to': trace['action'].get('to'),
                    'value': trace['action'].get('value'),
                    'gas_used': trace['result']['gasUsed'],
                    'contract_address': trace['result'].get('address'),
                    'output': trace['result'].get('output'),
                    'code': trace['result'].get('code'),
                    'call_type': call_type.value if call_type else None,
                }
            )
            internal_txs.append(internal_tx)
        return internal_txs
