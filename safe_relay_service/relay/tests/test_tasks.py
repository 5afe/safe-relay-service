import logging
from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from eth_account import Account

from ..models import EthereumTx
from ..services import Erc20EventsServiceProvider
from ..tasks import (
    check_and_update_pending_transactions,
    check_balance_of_accounts_task,
    check_pending_transactions,
    deploy_create2_safe_task,
    find_erc_20_721_transfers_task,
)
from .factories import SafeCreation2Factory, SafeMultisigTxFactory, SafeTxStatusFactory
from .relay_test_case import RelayTestCaseMixin

logger = logging.getLogger(__name__)

GAS_PRICE = settings.FIXED_GAS_PRICE


class TestTasks(RelayTestCaseMixin, TestCase):
    def test_deploy_create2_safe_task(self):
        safe_creation2 = self.create2_test_safe_in_db()

        safe_address = safe_creation2.safe.address
        deploy_create2_safe_task.delay(safe_address, False).get()
        safe_creation2.refresh_from_db()
        self.assertIsNone(safe_creation2.tx_hash)

        self.send_ether(to=safe_address, value=safe_creation2.payment)
        deploy_create2_safe_task.delay(safe_address, False).get()
        safe_creation2.refresh_from_db()
        self.assertIsNotNone(safe_creation2.tx_hash)

    def test_check_balance_of_accounts_task(self):
        self.assertTrue(check_balance_of_accounts_task.delay().get())

    def test_find_erc_20_721_transfers_task(self):
        erc20_events_service = Erc20EventsServiceProvider()
        erc20_events_service.confirmations = 0
        self.assertEqual(find_erc_20_721_transfers_task.delay().get(), 0)

        safe_creation_2 = SafeCreation2Factory(block_number=10)
        safe = safe_creation_2.safe
        safe_address = safe.address
        amount = 10
        owner_account = self.ethereum_test_account
        erc20_contract = self.deploy_example_erc20(
            amount, self.ethereum_test_account.address
        )
        self.send_tx(
            erc20_contract.functions.transfer(
                safe_address, amount // 2
            ).buildTransaction({"from": owner_account.address}),
            owner_account,
        )

        self.assertEqual(find_erc_20_721_transfers_task.delay().get(), 0)
        SafeTxStatusFactory(safe=safe)
        self.assertEqual(find_erc_20_721_transfers_task.delay().get(), 1)
        Erc20EventsServiceProvider.del_singleton()

    def test_check_pending_transactions(self):
        not_mined_alert_minutes = settings.SAFE_TX_NOT_MINED_ALERT_MINUTES
        self.assertEqual(check_pending_transactions.delay().get(), 0)

        SafeMultisigTxFactory(
            created=timezone.now() - timedelta(minutes=not_mined_alert_minutes - 1),
            ethereum_tx__block=None,
        )
        self.assertEqual(check_pending_transactions.delay().get(), 0)

        SafeMultisigTxFactory(
            created=timezone.now() - timedelta(minutes=not_mined_alert_minutes + 1),
            ethereum_tx__block=None,
        )
        self.assertEqual(check_pending_transactions.delay().get(), 1)

    def test_check_and_update_pending_transactions(self):
        SafeMultisigTxFactory(
            created=timezone.now() - timedelta(seconds=151), ethereum_tx__block=None
        )
        self.assertEqual(check_and_update_pending_transactions.delay().get(), 0)

        tx_hash = self.send_ether(Account.create().address, 1)
        SafeMultisigTxFactory(
            created=timezone.now() - timedelta(seconds=151),
            ethereum_tx__tx_hash=tx_hash,
            ethereum_tx__block=None,
        )
        self.assertEqual(check_and_update_pending_transactions.delay().get(), 1)
        self.assertGreaterEqual(EthereumTx.objects.get(tx_hash=tx_hash).block_id, 0)
