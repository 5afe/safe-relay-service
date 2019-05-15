from logging import getLogger
from typing import Dict, List, Set

from gnosis.eth import EthereumClient

from ..models import EthereumTxCallType, InternalTx
from .transaction_scan_service import TransactionScanService

logger = getLogger(__name__)


class InternalTxServiceProvider:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            from django.conf import settings
            cls.instance = InternalTxService(EthereumClient(settings.ETHEREUM_TRACING_NODE_URL),
                                             block_process_limit=settings.INTERNAL_TXS_BLOCK_PROCESS_LIMIT)
        return cls.instance

    @classmethod
    def del_singleton(cls):
        if hasattr(cls, "instance"):
            del cls.instance


class InternalTxService(TransactionScanService):
    @property
    def database_field(self):
        return 'tx_block_number'

    def find_relevant_tx_hashes(self, safe_addresses: List[str], from_block_number: int,
                                to_block_number: int) -> Set[str]:
        """
        Search for tx hashes with internal txs (in and out) of a `safe_address`
        :param safe_addresses:
        :param from_block_number: Starting block number
        :param to_block_number: Ending block number
        :return: Tx hashes of txs with internal txs relevant for the `safe_addresses`
        """
        logger.debug('Searching for internal txs from block-number=%d to block-number=%d - Safes=%s',
                     from_block_number, to_block_number, safe_addresses)

        to_traces = self.ethereum_client.parity.trace_filter(from_block=from_block_number,
                                                             to_block=to_block_number,
                                                             to_address=safe_addresses)

        from_traces = self.ethereum_client.parity.trace_filter(from_block=from_block_number,
                                                               to_block=to_block_number,
                                                               from_address=safe_addresses)

        # Log INFO if traces found, DEBUG if not
        log_fn = logger.info if to_traces + from_traces else logger.debug
        log_fn('Found %d relevant txs between block-number=%d and block-number%d. Safes=%s',
               len(to_traces + from_traces), from_block_number, to_block_number, safe_addresses)

        return set([trace['transactionHash'] for trace in (to_traces + from_traces)])

    def process_tx_hash(self, tx_hash: str) -> List[InternalTx]:
        """
        Search on Ethereum and store internal txs for provided `tx_hash`
        :param tx_hash:
        :return: List of `InternalTx` already stored in database
        """
        return self._process_traces(self.ethereum_client.parity.trace_transaction(tx_hash))

    def _process_trace(self, trace: Dict[str, any]) -> InternalTx:
        ethereum_tx = self.create_or_update_ethereum_tx(trace['transactionHash'])
        call_type = EthereumTxCallType.parse_call_type(trace['action'].get('callType'))
        trace_address_str = ','.join([str(address) for address in trace['traceAddress']])
        internal_tx, _ = InternalTx.objects.get_or_create(
            ethereum_tx=ethereum_tx,
            trace_address=trace_address_str,
            defaults={
                '_from': trace['action']['from'],
                'gas': trace['action']['gas'],
                'data': trace['action'].get('input') or trace['action'].get('init'),
                'to': trace['action'].get('to'),
                'value': trace['action'].get('value'),
                'gas_used': trace.get('result', {}).get('gasUsed', 0),
                'contract_address': trace.get('result', {}).get('address'),
                'output': trace.get('result', {}).get('output'),
                'code': trace.get('result', {}).get('code'),
                'call_type': call_type.value if call_type else None,
                'error': trace.get('error'),
            }
        )
        return internal_tx

    def _process_traces(self, traces: List[Dict[str, any]]) -> List[InternalTx]:
        return [self._process_trace(trace) for trace in traces]
