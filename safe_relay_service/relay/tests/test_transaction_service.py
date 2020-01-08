from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from eth_account import Account
from hexbytes import HexBytes

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.contracts import get_paying_proxy_contract, get_safe_contract
from gnosis.eth.utils import get_eth_address_with_key
from gnosis.safe import CannotEstimateGas, Safe, SafeOperation

from safe_relay_service.tokens.tests.factories import TokenFactory

from ..services.transaction_service import (GasPriceTooLow, InvalidGasToken,
                                            InvalidMasterCopyAddress,
                                            InvalidProxyContract,
                                            InvalidRefundReceiver,
                                            NotEnoughFundsForMultisigTx,
                                            RefundMustBeEnabled,
                                            SignaturesNotSorted)
from .factories import SafeContractFactory, SafeMultisigTxFactory
from .relay_test_case import RelayTestCaseMixin


class TestTransactionService(RelayTestCaseMixin, TestCase):
    def test_create_multisig_tx(self):
        w3 = self.w3

        # The balance we will send to the safe
        safe_balance = w3.toWei(0.02, 'ether')

        # Create Safe
        funder_account = self.ethereum_test_account
        funder = funder_account.address
        accounts = [self.create_account(), self.create_account()]
        # Signatures must be sorted!
        accounts.sort(key=lambda account: account.address.lower())
        owners = [x.address for x in accounts]
        threshold = len(accounts)

        safe_creation = self.deploy_test_safe(owners=owners, threshold=threshold)
        my_safe_address = safe_creation.safe_address
        my_safe_contract = get_safe_contract(w3, my_safe_address)
        SafeContractFactory(address=my_safe_address)

        to = funder
        value = safe_balance // 4
        data = HexBytes('')
        operation = 0
        safe_tx_gas = 100000
        data_gas = 300000
        gas_price = self.transaction_service._get_minimum_gas_price()
        gas_token = NULL_ADDRESS
        refund_receiver = NULL_ADDRESS
        safe = Safe(my_safe_address, self.ethereum_client)
        nonce = safe.retrieve_nonce()
        safe_multisig_tx_hash = safe.build_multisig_tx(to,
                                                       value,
                                                       data,
                                                       operation,
                                                       safe_tx_gas,
                                                       data_gas,
                                                       gas_price,
                                                       gas_token,
                                                       refund_receiver,
                                                       safe_nonce=nonce).safe_tx_hash

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

        invalid_proxy = self.deploy_example_erc20(1, NULL_ADDRESS)
        with self.assertRaises(InvalidProxyContract):
            SafeContractFactory(address=invalid_proxy.address)
            self.transaction_service.create_multisig_tx(
                invalid_proxy.address,
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

        # Use invalid master copy
        random_master_copy = Account.create().address
        proxy_create_tx = get_paying_proxy_contract(self.w3
                                                    ).constructor(random_master_copy, b'',
                                                                  NULL_ADDRESS,
                                                                  NULL_ADDRESS, 0
                                                                  ).buildTransaction({'from': self.ethereum_test_account.address})
        tx_hash = self.ethereum_client.send_unsigned_transaction(proxy_create_tx, private_key=self.ethereum_test_account.key)
        tx_receipt = self.ethereum_client.get_transaction_receipt(tx_hash, timeout=60)
        proxy_address = tx_receipt.contractAddress
        with self.assertRaises(InvalidMasterCopyAddress):
            SafeContractFactory(address=proxy_address)
            self.transaction_service.create_multisig_tx(
                proxy_address,
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

        with self.assertRaises(NotEnoughFundsForMultisigTx):
            self.transaction_service.create_multisig_tx(
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
            self.transaction_service.create_multisig_tx(
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
            self.transaction_service.create_multisig_tx(
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
            self.transaction_service.create_multisig_tx(
                my_safe_address,
                to,
                value,
                data,
                operation,
                safe_tx_gas,
                data_gas,
                self.transaction_service._get_minimum_gas_price() - 1,
                gas_token,
                refund_receiver,
                nonce,
                signatures,
                )

        with self.assertRaises(InvalidGasToken):
            invalid_gas_token = Account.create().address
            self.transaction_service.create_multisig_tx(
                my_safe_address,
                to,
                value,
                data,
                operation,
                safe_tx_gas,
                data_gas,
                gas_price,
                invalid_gas_token,
                refund_receiver,
                nonce,
                reversed(signatures)
            )

        with self.assertRaises(SignaturesNotSorted):
            self.transaction_service.create_multisig_tx(
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

        sender = self.transaction_service.tx_sender_account.address
        sender_balance = w3.eth.getBalance(sender)
        safe_balance = w3.eth.getBalance(my_safe_address)

        safe_multisig_tx = self.transaction_service.create_multisig_tx(
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

        tx_receipt = w3.eth.waitForTransactionReceipt(safe_multisig_tx.ethereum_tx.tx_hash)
        self.assertTrue(tx_receipt['status'])
        self.assertEqual(w3.toChecksumAddress(tx_receipt['from']), sender)
        self.assertEqual(w3.toChecksumAddress(tx_receipt['to']), my_safe_address)
        self.assertGreater(safe_multisig_tx.ethereum_tx.gas_price, gas_price)  # We used minimum gas price

        sender_new_balance = w3.eth.getBalance(sender)
        gas_used = tx_receipt['gasUsed']
        tx_fees = gas_used * safe_multisig_tx.ethereum_tx.gas_price
        estimated_refund = (safe_multisig_tx.data_gas + safe_multisig_tx.safe_tx_gas) * safe_multisig_tx.gas_price
        real_refund = safe_balance - w3.eth.getBalance(my_safe_address) - value
        # Real refund can be less if not all the `safe_tx_gas` is used
        self.assertGreaterEqual(estimated_refund, real_refund)
        self.assertEqual(sender_new_balance, sender_balance - tx_fees + real_refund)
        self.assertEqual(safe.retrieve_nonce(), 1)

        # Send again the tx and check that works
        nonce += 1
        value = 0
        safe_multisig_tx_hash = safe.build_multisig_tx(to,
                                                       value,
                                                       data,
                                                       operation,
                                                       safe_tx_gas,
                                                       data_gas,
                                                       gas_price,
                                                       gas_token,
                                                       refund_receiver,
                                                       safe_nonce=nonce).safe_tx_hash

        signatures = [account.signHash(safe_multisig_tx_hash) for account in accounts]

        safe_multisig_tx = self.transaction_service.create_multisig_tx(
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
        tx_receipt = w3.eth.waitForTransactionReceipt(safe_multisig_tx.ethereum_tx.tx_hash)
        self.assertTrue(tx_receipt['status'])

    def test_estimate_tx(self):
        safe_address = Account.create().address
        to = Account.create().address
        value = 0
        data = b''
        operation = SafeOperation.CALL.value
        gas_token = Account().create().address

        with self.assertRaises(InvalidGasToken):
            self.transaction_service.estimate_tx(safe_address, to, value, data, operation, gas_token)

        TokenFactory(address=gas_token, gas=True)
        with self.assertRaises(CannotEstimateGas):
            self.transaction_service.estimate_tx(safe_address, to, value, data, operation, gas_token)

        # We need a real safe deployed for this method to work
        gas_token = NULL_ADDRESS
        safe_address = self.deploy_test_safe().safe_address
        transaction_estimation = self.transaction_service.estimate_tx(safe_address, to, value, data, operation, gas_token)
        self.assertEqual(transaction_estimation.last_used_nonce, None)
        self.assertGreater(transaction_estimation.safe_tx_gas, 0)
        self.assertGreater(transaction_estimation.base_gas, 0)
        self.assertGreater(transaction_estimation.data_gas, 0)
        self.assertGreater(transaction_estimation.gas_price, 0)
        self.assertEqual(transaction_estimation.operational_gas, 0)
        self.assertEqual(transaction_estimation.gas_token, NULL_ADDRESS)
        #TODO Test operational gas for old safes

    def test_estimate_tx_for_all_tokent(self):
        safe_address = self.deploy_test_safe().safe_address
        to = Account.create().address
        value = 0
        data = b''
        operation = SafeOperation.CALL.value

        # TokenFactory(address=gas_token, gas=True)
        transaction_estimations = self.transaction_service.estimate_tx_for_all_tokens(safe_address, to, value,
                                                                                      data, operation)
        self.assertEqual(transaction_estimations.last_used_nonce, None)
        self.assertGreater(transaction_estimations.safe_tx_gas, 0)
        self.assertEqual(transaction_estimations.operational_gas, 0)  # Operational gas must be `0` for new Safes
        self.assertEqual(len(transaction_estimations.estimations), 1)  # Just ether
        estimation = transaction_estimations.estimations[0]
        self.assertGreater(estimation.gas_price, 0)
        self.assertGreater(estimation.base_gas, 0)
        self.assertEqual(estimation.gas_token, NULL_ADDRESS)

        TokenFactory(address=Account.create().address, gas=True, fixed_eth_conversion=None)
        transaction_estimations = self.transaction_service.estimate_tx_for_all_tokens(safe_address, to, value,
                                                                                      data, operation)
        self.assertEqual(len(transaction_estimations.estimations), 1)  # Just ether as no price was configured

        valid_token = TokenFactory(address=Account.create().address, gas=True, fixed_eth_conversion=2)
        transaction_estimations = self.transaction_service.estimate_tx_for_all_tokens(safe_address, to, value,
                                                                                      data, operation)
        self.assertEqual(transaction_estimations.last_used_nonce, None)
        self.assertGreater(transaction_estimations.safe_tx_gas, 0)
        self.assertEqual(transaction_estimations.operational_gas, 0)  # Operational gas must be `0` for new Safes
        self.assertEqual(len(transaction_estimations.estimations), 2)  # Just ether
        estimation_ether = transaction_estimations.estimations[0]
        self.assertGreater(estimation_ether.gas_price, 0)
        self.assertGreater(estimation_ether.base_gas, 0)
        self.assertEqual(estimation_ether.gas_token, NULL_ADDRESS)
        estimation_token = transaction_estimations.estimations[1]
        self.assertAlmostEqual(estimation_token.gas_price, estimation_ether.gas_price // 2, delta=1.0)
        self.assertGreater(estimation_token.base_gas, estimation_ether.base_gas)
        self.assertEqual(estimation_token.gas_token, valid_token.address)

    def test_get_pending_multisig_transactions(self):
        self.assertFalse(self.transaction_service.get_pending_multisig_transactions(0))

        SafeMultisigTxFactory(created=timezone.now())
        self.assertFalse(self.transaction_service.get_pending_multisig_transactions(0))

        SafeMultisigTxFactory(created=timezone.now(), ethereum_tx__block=None)
        self.assertEqual(self.transaction_service.get_pending_multisig_transactions(0).count(), 1)
        self.assertFalse(self.transaction_service.get_pending_multisig_transactions(30))

        SafeMultisigTxFactory(created=timezone.now() - timedelta(seconds=60), ethereum_tx__block=None)
        self.assertEqual(self.transaction_service.get_pending_multisig_transactions(30).count(), 1)
        SafeMultisigTxFactory(created=timezone.now() - timedelta(minutes=60), ethereum_tx__block=None)
        self.assertEqual(self.transaction_service.get_pending_multisig_transactions(30).count(), 2)
