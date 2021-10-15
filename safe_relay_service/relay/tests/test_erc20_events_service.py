from django.db.models import Q
from django.test import TestCase

from gnosis.safe.tests.safe_test_case import SafeTestCaseMixin

from ..models import EthereumEvent, SafeTxStatus
from ..services import Erc20EventsService
from .factories import SafeContractFactory, SafeTxStatusFactory


class TestErc20EventsService(SafeTestCaseMixin, TestCase):
    def test_erc20_process_addresses(self):
        block_process_limit = 1
        confirmations = 10
        erc20_events_service = Erc20EventsService(
            self.ethereum_client,
            confirmations=confirmations,
            block_process_limit=block_process_limit,
        )

        with self.assertRaisesMessage(AssertionError, "Safe addresses cannot be empty"):
            erc20_events_service.process_addresses([])

        amount = 50
        owner_account = self.create_account(initial_ether=0.01)
        account_1 = self.create_account(initial_ether=0.01)
        safe_address = account_1.address
        safe_contract = SafeContractFactory(address=safe_address)
        account_2 = self.create_account(initial_ether=0.01)
        account_3 = self.create_account(initial_ether=0.01)
        erc20_contract = self.deploy_example_erc20(amount, owner_account.address)

        # We send some tx, Ganache mines one block by every tx
        # `owner` sends `amount // 2` to `account_1` and `account_3`
        to_tx_hash = self.send_tx(
            erc20_contract.functions.transfer(
                account_1.address, amount // 2
            ).buildTransaction({"from": owner_account.address}),
            owner_account,
        )
        self.send_tx(
            erc20_contract.functions.transfer(
                account_3.address, amount // 2
            ).buildTransaction({"from": owner_account.address}),
            owner_account,
        )
        # `account1` sends `amount // 2` (all) to `account_2`
        from_tx_hash = self.send_tx(
            erc20_contract.functions.transfer(
                account_2.address, amount // 2
            ).buildTransaction({"from": account_1.address}),
            account_1,
        )

        # Will not index anything as no `SafeTxStatus` exists
        self.assertIsNone(erc20_events_service.process_addresses([safe_address]))
        self.assertEqual(SafeTxStatus.objects.filter(safe=safe_contract).count(), 0)
        self.assertEqual(
            EthereumEvent.objects.filter(
                Q(arguments__from=safe_address) | Q(arguments__to=safe_address)
            ).count(),
            0,
        )
        SafeTxStatusFactory(safe=safe_contract)

        # Now it will scan 1 block, but nothing will appear for this new address
        _, updated = erc20_events_service.process_addresses([safe_address])
        self.assertFalse(updated)
        safe_tx_status = SafeTxStatus.objects.get(safe=safe_contract)
        self.assertEqual(safe_tx_status.erc_20_block_number, block_process_limit)

        # We scan for every tx, but will not find anything because of the default confirmations
        erc20_events_service.block_process_limit = 0
        _, updated = erc20_events_service.process_addresses([safe_address])
        self.assertTrue(updated)
        safe_tx_status = SafeTxStatus.objects.get(safe=safe_contract)
        self.assertEqual(
            safe_tx_status.erc_20_block_number,
            erc20_events_service.ethereum_client.current_block_number - confirmations,
        )
        self.assertEqual(EthereumEvent.objects.count(), 0)

        erc20_events_service.confirmations = 0
        _, updated = erc20_events_service.process_addresses([safe_address])
        self.assertTrue(updated)
        safe_tx_status = SafeTxStatus.objects.get(safe=safe_contract)
        self.assertEqual(
            safe_tx_status.erc_20_block_number,
            erc20_events_service.ethereum_client.current_block_number,
        )
        self.assertEqual(EthereumEvent.objects.count(), 2)
        self.assertEqual(
            EthereumEvent.objects.filter(
                Q(arguments__from=safe_address) | Q(arguments__to=safe_address)
            ).count(),
            2,
        )
        self.assertEqual(
            EthereumEvent.objects.get(arguments__from=safe_address).ethereum_tx_id,
            from_tx_hash.hex(),
        )
        self.assertEqual(
            EthereumEvent.objects.get(arguments__to=safe_address).ethereum_tx_id,
            to_tx_hash.hex(),
        )
        for erc20_event in EthereumEvent.objects.erc20_events():
            self.assertEqual(
                erc20_event.topic, self.ethereum_client.erc20.TRANSFER_TOPIC.hex()
            )
        self.assertEqual(EthereumEvent.objects.erc20_events().count(), 2)
        self.assertEqual(EthereumEvent.objects.erc721_events().count(), 0)
