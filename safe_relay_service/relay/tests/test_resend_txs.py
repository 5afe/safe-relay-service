from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from eth_account import Account
from hexbytes import HexBytes

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.safe import Safe

from ..management.commands import resend_txs
from ..models import SafeMultisigTx
from .relay_test_case import RelayTestCaseMixin


class TestResendTxsCommand(RelayTestCaseMixin, TestCase):
    def test_resend_txs(self):
        # Nothing happens
        call_command(resend_txs.Command())

        w3 = self.w3
        # The balance we will send to the safe
        safe_balance = w3.toWei(0.02, "ether")

        # Create Safe
        accounts = [self.create_account(), self.create_account()]

        # Signatures must be sorted!
        accounts.sort(key=lambda account: account.address.lower())

        safe = self.deploy_test_safe(
            owners=[x.address for x in accounts],
            threshold=len(accounts),
            initial_funding_wei=safe_balance,
        )
        my_safe_address = safe.address

        to = Account().create().address
        value = safe_balance // 4
        data = HexBytes("")
        operation = 0
        safe_tx_gas = 100000
        data_gas = 300000
        gas_price = self.transaction_service._get_minimum_gas_price()
        gas_token = NULL_ADDRESS
        refund_receiver = NULL_ADDRESS
        safe = Safe(my_safe_address, self.ethereum_client)
        nonce = safe.retrieve_nonce()
        safe_multisig_tx_hash = safe.build_multisig_tx(
            to,
            value,
            data,
            operation,
            safe_tx_gas,
            data_gas,
            gas_price,
            gas_token,
            refund_receiver,
            safe_nonce=nonce,
        ).safe_tx_hash

        signatures = [account.signHash(safe_multisig_tx_hash) for account in accounts]
        sender = self.transaction_service.tx_sender_account.address

        # Ganache snapshot
        snapshot_id = w3.testing.snapshot()
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

        tx_receipt = w3.eth.wait_for_transaction_receipt(
            safe_multisig_tx.ethereum_tx.tx_hash
        )
        self.assertTrue(tx_receipt["status"])
        self.assertEqual(w3.toChecksumAddress(tx_receipt["from"]), sender)
        self.assertEqual(w3.toChecksumAddress(tx_receipt["to"]), my_safe_address)
        self.assertEqual(w3.eth.get_balance(to), value)

        w3.testing.revert(snapshot_id)  # Revert to snapshot in ganache
        snapshot_id = w3.testing.snapshot()
        self.assertEqual(w3.eth.get_balance(to), 0)

        old_multisig_tx: SafeMultisigTx = SafeMultisigTx.objects.all().first()
        old_multisig_tx.created = timezone.now() - timedelta(days=1)
        old_multisig_tx.save()
        new_gas_price = old_multisig_tx.ethereum_tx.gas_price + 1  # Gas price increased

        call_command(resend_txs.Command(), gas_price=new_gas_price)
        multisig_tx: SafeMultisigTx = SafeMultisigTx.objects.all().first()
        self.assertNotEqual(multisig_tx.ethereum_tx_id, old_multisig_tx.ethereum_tx_id)
        self.assertEqual(multisig_tx.ethereum_tx.gas_price, new_gas_price)
        self.assertEqual(w3.eth.get_balance(to), value)  # Tx is executed again
        self.assertEqual(
            multisig_tx.get_safe_tx(self.ethereum_client).__dict__,
            old_multisig_tx.get_safe_tx(self.ethereum_client).__dict__,
        )

        w3.testing.revert(snapshot_id)  # Revert to snapshot in ganache
        self.assertEqual(w3.eth.get_balance(to), 0)

        old_multisig_tx: SafeMultisigTx = SafeMultisigTx.objects.all().first()
        old_multisig_tx.created = timezone.now() - timedelta(days=1)
        old_multisig_tx.save()
        new_gas_price = old_multisig_tx.ethereum_tx.gas_price  # Gas price is the same

        call_command(resend_txs.Command(), gas_price=new_gas_price)
        multisig_tx: SafeMultisigTx = SafeMultisigTx.objects.all().first()
        self.assertEqual(multisig_tx.ethereum_tx_id, old_multisig_tx.ethereum_tx_id)
        self.assertEqual(multisig_tx.ethereum_tx.gas_price, new_gas_price)
        self.assertEqual(w3.eth.get_balance(to), value)  # Tx is executed again
        self.assertEqual(
            multisig_tx.get_safe_tx(self.ethereum_client).__dict__,
            old_multisig_tx.get_safe_tx(self.ethereum_client).__dict__,
        )
