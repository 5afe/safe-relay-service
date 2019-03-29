import logging
from eth_account import Account

from hexbytes import HexBytes

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.contracts import get_safe_contract
from gnosis.eth.utils import get_eth_address_with_key
from gnosis.safe.tests.test_safe_service import TestSafeService

from .factories import SafeContractFactory
from ..services.transaction_service import (GasPriceTooLow,
                                            InvalidRefundReceiver,
                                            NotEnoughFundsForMultisigTx,
                                            RefundMustBeEnabled,
                                            TransactionServiceProvider, SignaturesNotSorted)

logger = logging.getLogger(__name__)


class TestTransactionService(TestSafeService):

    def test_transaction_provider_singleton(self):
        service1 = TransactionServiceProvider()
        service2 = TransactionServiceProvider()
        self.assertEqual(service1, service2)

    def test_create_multisig_tx(self):
        w3 = self.w3
        transaction_service = TransactionServiceProvider()
        gas_station = transaction_service.gas_station

        # The balance we will send to the safe
        safe_balance = w3.toWei(0.02, 'ether')
        # Send something to the owner[0], who will be sending the tx
        owner0_balance = safe_balance

        # Create Safe
        funder_account = self.ethereum_test_account
        funder = funder_account.address
        accounts = [self.create_account(initial_wei=owner0_balance), self.create_account(initial_wei=owner0_balance)]
        # Signatures must be sorted!
        accounts.sort(key=lambda account: account.address.lower())
        owners = [x.address for x in accounts]
        threshold = len(accounts)

        safe_creation = self.deploy_test_safe(owners=owners, threshold=threshold)
        my_safe_address = safe_creation.safe_address
        my_safe_contract = get_safe_contract(w3, my_safe_address)
        SafeContractFactory(address=my_safe_address)

        to = funder
        value = safe_balance // 2
        data = HexBytes('')
        operation = 0
        safe_tx_gas = 100000
        data_gas = 300000
        gas_price = gas_station.get_gas_prices().fast
        gas_token = NULL_ADDRESS
        refund_receiver = NULL_ADDRESS
        nonce = self.safe_service.retrieve_nonce(my_safe_address)
        safe_multisig_tx_hash = self.safe_service.get_hash_for_safe_tx(safe_address=my_safe_address,
                                                                       to=to,
                                                                       value=value,
                                                                       data=data,
                                                                       operation=operation,
                                                                       safe_tx_gas=safe_tx_gas,
                                                                       data_gas=data_gas,
                                                                       gas_price=gas_price,
                                                                       gas_token=gas_token,
                                                                       refund_receiver=refund_receiver,
                                                                       nonce=nonce)

        # Just to make sure we are not miscalculating tx_hash
        contract_multisig_tx_hash = my_safe_contract.functions.getTransactionHash(
            to,
            value,
            data,
            operation,
            safe_tx_gas,
            data_gas,
            gas_price,
            gas_token,
            refund_receiver,
            nonce).call()

        self.assertEqual(safe_multisig_tx_hash, contract_multisig_tx_hash)

        signatures = [account.signHash(safe_multisig_tx_hash) for account in accounts]

        # Check owners are the same
        contract_owners = my_safe_contract.functions.getOwners().call()
        self.assertEqual(set(contract_owners), set(owners))
        self.assertEqual(w3.eth.getBalance(owners[0]), owner0_balance)

        with self.assertRaises(NotEnoughFundsForMultisigTx):
            transaction_service.create_multisig_tx(
                my_safe_address,
                to,
                value,
                data,
                operation,
                safe_tx_gas,
                data_gas,
                gas_price,
                gas_token,
                refund_receiver,
                nonce,
                signatures,
            )

        # Send something to the safe
        self.send_tx({
            'to': my_safe_address,
            'value': safe_balance
        }, funder_account)

        bad_refund_receiver = get_eth_address_with_key()[0]
        with self.assertRaises(InvalidRefundReceiver):
            transaction_service.create_multisig_tx(
                my_safe_address,
                to,
                value,
                data,
                operation,
                safe_tx_gas,
                data_gas,
                gas_price,
                gas_token,
                bad_refund_receiver,
                nonce,
                signatures,
            )

        invalid_gas_price = 0
        with self.assertRaises(RefundMustBeEnabled):
            transaction_service.create_multisig_tx(
                my_safe_address,
                to,
                value,
                data,
                operation,
                safe_tx_gas,
                data_gas,
                invalid_gas_price,
                gas_token,
                refund_receiver,
                nonce,
                signatures,
            )

        with self.assertRaises(GasPriceTooLow):
            transaction_service.create_multisig_tx(
                my_safe_address,
                to,
                value,
                data,
                operation,
                safe_tx_gas,
                data_gas,
                gas_station.get_gas_prices().standard - 1,
                gas_token,
                refund_receiver,
                nonce,
                signatures,
            )

        with self.assertRaises(SignaturesNotSorted):
            transaction_service.create_multisig_tx(
                my_safe_address,
                to,
                value,
                data,
                operation,
                safe_tx_gas,
                data_gas,
                gas_price,
                gas_token,
                refund_receiver,
                nonce,
                reversed(signatures)
            )

        sender = transaction_service.tx_sender_account.address
        sender_balance = w3.eth.getBalance(sender)
        safe_balance = w3.eth.getBalance(my_safe_address)

        safe_multisig_tx = transaction_service.create_multisig_tx(
            my_safe_address,
            to,
            value,
            data,
            operation,
            safe_tx_gas,
            data_gas,
            gas_price,
            gas_token,
            refund_receiver,
            nonce,
            signatures,
        )

        tx_receipt = w3.eth.waitForTransactionReceipt(safe_multisig_tx.tx_hash)
        self.assertTrue(tx_receipt['status'])
        self.assertEqual(w3.toChecksumAddress(tx_receipt['from']), sender)
        self.assertEqual(w3.toChecksumAddress(tx_receipt['to']), my_safe_address)

        sender_new_balance = w3.eth.getBalance(sender)
        gas_used = tx_receipt['gasUsed']
        tx_fees = gas_used * gas_price
        estimated_refund = (safe_multisig_tx.data_gas + safe_multisig_tx.safe_tx_gas) * safe_multisig_tx.gas_price
        real_refund = safe_balance - w3.eth.getBalance(my_safe_address) - value
        # Real refund can be less if not all the `safe_tx_gas` is used
        self.assertGreaterEqual(estimated_refund, real_refund)
        self.assertEqual(sender_new_balance, sender_balance - tx_fees + real_refund)
        self.assertEqual(self.safe_service.retrieve_nonce(my_safe_address), 1)
