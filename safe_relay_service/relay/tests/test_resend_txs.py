from datetime import timedelta

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from gnosis.eth.tests.ethereum_test_case import EthereumTestCaseMixin

from ..management.commands import resend_txs
from .factories import SafeMultisigTxFactory


class TestResendTxsCommand(EthereumTestCaseMixin, TestCase):
    def test_resend_txs(self):
        multisig_tx = SafeMultisigTxFactory(ethereum_tx__block=None)
        call_command(resend_txs.Command())
        multisig_tx.created = timezone.now() - timedelta(days=1)
        multisig_tx.save()
        with self.assertRaises(ValueError):
            call_command(resend_txs.Command(), gas_price=multisig_tx.ethereum_tx.gas_price + 1)
        #TODO More testing
