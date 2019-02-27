import math
import os
import random
import requests
from logging import getLogger
from typing import Dict, List, Tuple, Union

import rlp
from django_eth.constants import NULL_ADDRESS
from eth_account.internal.transactions import (encode_transaction,
                                               serializable_unsigned_transaction_from_dict)
from ethereum.exceptions import InvalidTransaction
from ethereum.transactions import Transaction, secpk1n
from ethereum.utils import checksum_encode, mk_contract_address, normalize_address, sha3, normalize_key
from hexbytes import HexBytes
from web3 import Web3
from .abis import load_contract_interface
from Crypto.Hash import keccak

from .contracts import get_paying_proxyb_contract, get_paying_proxybootstrap_contract, get_safe_contract, \
    get_subscription_module, \
    get_proxy_factory_contract, get_wrapper_abi, get_create_add_modules, get_merchant_module

logger = getLogger(__name__)


class SafeCreationTx:
    def __init__(self, w3: Web3, wallet_type: str, owners: List[str], threshold: int, signature_s: int,
                 master_copy: str,
                 gas_price: int, funder: Union[str, None], payment_token: Union[str, None] = None,
                 payment_token_eth_value: float = 1.0, fixed_creation_cost: Union[int, None] = None):
        """
        Prepare Safe creation
        :param w3: Web3 instance
        :param owners: Owners of the Safe
        :param threshold: Minimum number of users required to operate the Safe
        :param signature_s: Random s value for ecdsa signature
        :param master_copy: Safe master copy address
        :param gas_price: Gas Price
        :param funder: Address to refund when the Safe is created. Address(0) if no need to refund
        :param payment_token: Payment token instead of paying the funder with ether. If None Ether will be used
        :param payment_token_eth_value: Value of payment token per 1 Ether
        :param fixed_creation_cost: Fixed creation cost of Safe (Wei)
        """

        assert 0 < threshold <= len(owners)
        self.wallet_type = wallet_type or "customer"
        self.owners = owners
        self.threshold = threshold
        self.s = signature_s
        self.master_copy = master_copy
        self.gas_price = gas_price
        self.funder = funder or NULL_ADDRESS

        self.payment_token = payment_token or NULL_ADDRESS
        self.subscription_module_address = checksum_encode('0x254dffcd3277C0b1660F6d42EFbB754edaBAbC2B')
        self.merchant_module_address = checksum_encode('0xD833215cBcc3f914bD1C9ece3EE7BF8B14f841bb')
        self.proxy_factory_address = checksum_encode('0xCfEB869F69431e42cdB54A4F4f105C19C080A601')
        self.create_add_modules_address = checksum_encode('0xe982E462b094850F12AF94d21D470e21bE9D0E9C')
        self.oracle_registry_address = checksum_encode('0x9b1f7F645351AF3631a656421eD2e40f2802E6c0')
        self.gnosis_safe_contract = get_safe_contract(w3, checksum_encode('0xe78A0F7E598Cc8b0Bb87894B0F60dD2a88d6a8Ab'))
        self.subscription_module_contract = get_subscription_module(w3, self.subscription_module_address)
        self.merchant_module_contract = get_merchant_module(w3, self.merchant_module_address)
        self.paying_proxy_contract = get_paying_proxybootstrap_contract(w3)
        self.proxy_factory_contract = get_proxy_factory_contract(w3, self.proxy_factory_address)
        self.wrapper_abi_contract = get_wrapper_abi(w3, checksum_encode("0x630589690929e9cdefdef0734717a9ef3ec7fcfe"))
        self.create_add_modules_contract = get_create_add_modules(w3, self.create_add_modules_address)
        safe_tx = self.get_initial_setup_safe_tx(owners, threshold)
        encoded_data = safe_tx['data']

        self.gas = self._calculate_gas(owners, encoded_data, payment_token)

        # Payment will be safe3 deploy cost + transfer fees for sending ether to the deployer
        self.payment_ether = (self.gas + 23000) * self.gas_price

        if fixed_creation_cost is None:
            # Calculate payment for tokens using the conversion (if used)
            self.payment = math.ceil(self.payment_ether / payment_token_eth_value)
        else:
            self.payment = fixed_creation_cost

        self.salt = self.uniqueId(32)
        self.contract_creation_tx_dict = self._build_proxy_contract_creation_tx(
            master_copy=self.master_copy,
            initializer=encoded_data,
            funder=self.funder,
            payment_token=self.payment_token,
            payment=self.payment,
            gas=self.gas,
            gas_price=self.gas_price,
            owners=owners,
            threshold=threshold,
            salt=self.salt
        )

        (self.contract_creation_tx,
         self.v,
         self.r) = self._generate_valid_transaction(
            self.proxy_factory_address,
            self.gas_price,
            self.gas,
            self.contract_creation_tx_dict['data'],
            self.s)
        self.raw_tx = rlp.encode(self.contract_creation_tx)
        self.tx_hash = self.contract_creation_tx.hash
        self.deployer_address = checksum_encode(self.contract_creation_tx.sender)

        middle_address = checksum_encode(mk_contract_address(self.deployer_address, nonce=0))
        self.cx_sub_module_address = checksum_encode(mk_contract_address(middle_address, nonce=1))
        self.safe_address = checksum_encode(mk_contract_address(middle_address, nonce=2))

    def mk_contract_create2(self, sender, salt, initcode):
        hash = sha3('0xff' + sender[2:] + str(salt) + str(sha3(initcode)))
        return hash[12:]

    def uniqueId(self, num):
        seed = random.getrandbits(num)
        return seed

    @staticmethod
    def find_valid_random_signature(s: int) -> Tuple[int, int]:
        """
        Find v and r valid values for a given s
        :param s: random value
        :return: v, r
        """
        for _ in range(10000):
            r = int(os.urandom(31).hex(), 16)
            v = (r % 2) + 27
            if r < secpk1n:
                tx = Transaction(0, 1, 21000, b'', 0, b'', v=v, r=r, s=s)
                try:
                    tx.sender
                    return v, r
                except (InvalidTransaction, ValueError):
                    logger.debug('Cannot find signature with v=%d r=%d s=%d', v, r, s)

        raise ValueError('Valid signature not found with s=%d', s)

    @staticmethod
    def _calculate_gas(owners: List[str], encoded_data: bytes, payment_token: str) -> int:
        # TODO Do gas calculation estimating the call instead this magic

        base_gas = 60580  # Transaction standard gas

        # TODO If we already have the token, we don't have to pay for storage, so it will be just 5K instead of 20K.
        # The other 1K is for overhead of making the call
        if payment_token != NULL_ADDRESS:
            payment_token_gas = 21000
        else:
            payment_token_gas = 0

        data_gas = 68 * len(encoded_data)  # Data gas
        gas_per_owner = 18020  # Magic number calculated by testing and averaging owners
        # return base_gas + data_gas + payment_token_gas + 270000 + len(owners) * gas_per_owner
        return 8000000

    def get_customer_module_data(self):

        groundhog_data = self.subscription_module_contract.functions.setup(
            self.oracle_registry_address
        ).buildTransaction({
            'gas': 1,
            'gasPrice': 1,
        })

        '''
        "exception": "ValueError: When using `ContractFunction.buildTransaction` from a contract factory you must provide a `to` address with the transaction"
        '''
        return groundhog_data

    def get_merchant_module_data(self):

        groundhog_data = self.merchant_module_contract.functions.setup(
            self.oracle_registry_address
        ).buildTransaction({
            'gas': 1,
            'gasPrice': 1,
        })

        '''
        "exception": "ValueError: When using `ContractFunction.buildTransaction` from a contract factory you must provide a `to` address with the transaction"
        '''
        return groundhog_data

    def get_initial_setup_safe_tx(self, owners: List[str], threshold: int) -> Dict[any, any]:
        # create_add_modules_data = self.get_subscription_module_data()
        # return self.gnosis_safe_contract.functions.setup(
        #     owners,
        #     threshold,
        #     NULL_ADDRESS,
        #     b''
        # ).buildTransaction({
        #     'gas': 1,
        #     'gasPrice': 1,
        # })

        module_data = self.get_customer_module_data()
        if self.wallet_type == "merchant":
            module_data = self.get_merchant_module_data()

        return module_data

    def _build_proxy_contract_creation_tx(self,
                                          master_copy: str,
                                          initializer: bytes,
                                          funder: str,
                                          payment_token: str,
                                          payment: int,
                                          gas: int,
                                          gas_price: int,
                                          owners: [str],
                                          threshold: int,
                                          salt: int,
                                          nonce: int = 0):
        """
        :param master_copy: Master Copy of Gnosis Safe already deployed
        :param initializer: Data initializer to send to GnosisSafe setup method
        :param funder: Address that should get the payment (if payment set)
        :param payment_token: Address if a token is used. If not set, 0x0 will be ether
        :param payment: Payment
        :return: Transaction dictionary
        """
        if not funder or funder == NULL_ADDRESS:
            funder = NULL_ADDRESS
            payment = 0

        module_master_copy = self.subscription_module_address
        if self.wallet_type == "merchant":
            module_master_copy = self.merchant_module_address

        return self.paying_proxy_contract.constructor(
            module_master_copy,
            master_copy,
            initializer,
            owners,
            threshold,
            self.create_add_modules_address,
            funder,
            payment_token,
            payment
        ).buildTransaction({
            'gas': gas,
            'gasPrice': gas_price,
        })

    def _generate_valid_transaction(self, to: str, gas_price: int, gas: int, data: str, s: int, nonce: int = 0) -> \
            Tuple[
                Transaction,
                int, int]:
        """
        :return: ContractCreationTx, v, r
        """
        zero_address = HexBytes('0x' + '0' * 40)
        f_address = HexBytes('0x' + 'f' * 40)
        for _ in range(100):
            try:
                v, r = self.find_valid_random_signature(s)
                # contract_creation_tx = Transaction(nonce, gas_price, gas, to, 0, HexBytes(data), v=v, r=r, s=s)
                contract_creation_tx = Transaction(nonce, gas_price, gas, b'', 0, HexBytes(data), v=v, r=r, s=s)
                sender = contract_creation_tx.sender
                if sender in (zero_address, f_address):
                    raise InvalidTransaction
                return contract_creation_tx, v, r
            except InvalidTransaction:
                pass
        raise ValueError('Valid signature not found with s=%d', s)

    @staticmethod
    def _sign_web3_transaction(tx: Dict[str, any], v: int, r: int, s: int) -> (bytes, HexBytes):
        """
        Signed transaction can be send with w3.eth.sendRawTransaction
        """
        unsigned_transaction = serializable_unsigned_transaction_from_dict(tx)
        rlp_encoded_transaction = encode_transaction(unsigned_transaction, vrs=(v, r, s))

        # To get the address signing, just do ecrecover_to_pub(unsigned_transaction.hash(), v, r, s)
        return rlp_encoded_transaction, unsigned_transaction.hash()
