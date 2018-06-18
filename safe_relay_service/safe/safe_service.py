from logging import getLogger
from typing import List, Tuple

import eth_abi
from django.conf import settings
from ethereum.utils import sha3
from hexbytes import HexBytes

from .contracts import get_safe_personal_contract
from .ethereum_service import EthereumService
from .utils import NULL_ADDRESS

logger = getLogger(__name__)


class NotValidMultisigTx(Exception):
    pass


class SafeService:
    def __new__(cls):
        if not hasattr(cls, 'instance'):
            cls.instance = super().__new__(cls)
        return cls.instance

    def __init__(self):
        self.ethereum_service = EthereumService()
        self.w3 = EthereumService().w3
        self.tx_sender_private_key = settings.SAFE_TX_SENDER_PRIVATE_KEY

    def send_multisig_tx(self,
                         safe: str,
                         to: str,
                         value: int,
                         data: bytes,
                         operation: int,
                         safe_tx_gas: int,
                         data_gas: int,
                         gas_price: int,
                         gas_token: str,
                         signatures: List[Tuple[int, int, int]],
                         tx_sender_private_key=None,
                         tx_gas=None,
                         tx_gas_price=None) -> Tuple[str, any]:
        """
        :param safe:
        :param to:
        :param value:
        :param data:
        :param operation:
        :param safe_tx_gas:
        :param data_gas:
        :param gas_price:
        :param gas_token:
        :param signatures:
        :param tx_sender_private_key:
        :param tx_gas:
        :param tx_gas_price:
        :return: tx_hash and tx
        """

        # TODO Calculate gas, calculate gas_price if None
        data = data or b''
        gas_token = gas_token or NULL_ADDRESS
        to = to or NULL_ADDRESS
        tx_gas = tx_gas or (safe_tx_gas + data_gas) * 2
        tx_gas_price = tx_gas_price or gas_price
        tx_sender_private_key = tx_sender_private_key or self.tx_sender_private_key

        paying_proxy_contract = get_safe_personal_contract(self.w3, address=safe)
        success = paying_proxy_contract.functions.execTransactionAndPaySubmitter(
            to,
            value,
            data,
            operation,
            safe_tx_gas,
            data_gas,
            gas_price,
            gas_token,
            signatures,
        ).call()

        if not success:
            raise NotValidMultisigTx

        tx_sender_address = self.ethereum_service.private_key_to_address(tx_sender_private_key)

        tx = paying_proxy_contract.functions.execTransactionAndPaySubmitter(
            to,
            value,
            data,
            operation,
            safe_tx_gas,
            data_gas,
            gas_price,
            gas_token,
            signatures,
        ).buildTransaction({
            'from': tx_sender_address,
            'gas': tx_gas,
            'gasPrice': tx_gas_price,
            'nonce': self.ethereum_service.get_nonce_for_account(tx_sender_address)
        })

        tx_signed = self.w3.eth.account.signTransaction(tx, tx_sender_private_key)

        return self.w3.eth.sendRawTransaction(tx_signed.rawTransaction), tx

    @staticmethod
    def get_hash_for_safe_tx(contract_address: str, to: str, value: int, data: bytes,
                             operation: int, safe_tx_gas: int, data_gas: int, gas_price: int,
                             gas_token: str, nonce: int) -> HexBytes:

        if not data:
            data = b''

        if not gas_token:
            gas_token = NULL_ADDRESS

        if not to:
            to = NULL_ADDRESS

        data_bytes = (
                bytes.fromhex('19') +
                bytes.fromhex('00') +
                HexBytes(contract_address) +
                HexBytes(to) +
                eth_abi.encode_single('uint256', value) +
                data +  # Data is always zero-padded to be even on solidity. So, 0x1 becomes 0x01
                operation.to_bytes(1, byteorder='big') +  # abi.encodePacked packs it on 1 byte
                eth_abi.encode_single('uint256', safe_tx_gas) +
                eth_abi.encode_single('uint256', data_gas) +
                eth_abi.encode_single('uint256', gas_price) +
                HexBytes(gas_token) +
                eth_abi.encode_single('uint256', nonce)
        )

        return HexBytes(sha3(data_bytes))

    def check_hash(self, tx_hash: str, signatures: bytes, owners: List[str]) -> bool:
        for i, owner in enumerate(sorted(owners, key=lambda x: x.lower())):
            v, r, s = self.signature_split(signatures, i)
            if self.ethereum_service.get_signing_address(tx_hash, v, r, s) != owner:
                return False
        return True

    def signature_split(self, signatures: bytes, pos: int) -> Tuple[int, int, int]:
        """
        :param signatures: signatures in form of {bytes32 r}{bytes32 s}{uint8 v}
        :param pos: position of the signature
        :return: Tuple with v, r, s
        """
        signature_pos = 65 * pos
        v = signatures[64 + signature_pos]
        r = int.from_bytes(signatures[signature_pos:32 + signature_pos], 'big')
        s = int.from_bytes(signatures[32 + signature_pos:64 + signature_pos], 'big')

        return v, r, s

    def signatures_to_bytes(self, signatures: List[Tuple[int, int, int]]) -> bytes:
        """
        Convert signatures to bytes
        :param signatures: list of v, r, s
        :return: 65 bytes per signature
        """
        return b''.join([self.signature_to_bytes(vrs) for vrs in signatures])

    @staticmethod
    def signature_to_bytes(vrs: Tuple[int, int, int]) -> bytes:
        """
        Convert signature to bytes
        :param vrs: tuple of v, r, s
        :return: signature in form of {bytes32 r}{bytes32 s}{uint8 v}
        """

        byte_order = 'big'

        v, r, s = vrs

        return (r.to_bytes(32, byteorder=byte_order) +
                s.to_bytes(32, byteorder=byte_order) +
                v.to_bytes(1, byteorder=byte_order))
