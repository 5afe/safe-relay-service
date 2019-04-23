import logging
from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from safe_relay_service.relay.services import InternalTxServiceProvider

from ..models import SafeContract, SafeFunding
from ..tasks import (check_balance_of_accounts_task,
                     check_deployer_funded_task, deploy_create2_safe_task,
                     deploy_safes_task, find_internal_txs_task,
                     fund_deployer_task)
from .factories import (SafeCreation2Factory, SafeCreationFactory,
                        SafeFundingFactory, SafeTxStatusFactory)
from .relay_test_case import RelayTestCaseMixin
from .test_internal_tx_service import EthereumClientMock

logger = logging.getLogger(__name__)

GAS_PRICE = settings.FIXED_GAS_PRICE


class TestTasks(RelayTestCaseMixin, TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.prepare_tests()

    def test_balance_in_deployer(self):
        safe_creation = self.create_test_safe_in_db()
        safe, deployer, payment = safe_creation.safe.address, safe_creation.deployer, safe_creation.payment

        self.send_ether(to=safe, value=payment)

        # If deployer has balance already no ether is sent to the account
        deployer_payment = 1
        self.send_ether(to=deployer, value=deployer_payment)

        self.assertEqual(self.ethereum_client.get_balance(deployer), deployer_payment)

        fund_deployer_task.delay(safe, retry=False).get()

        self.assertEqual(self.ethereum_client.get_balance(deployer), deployer_payment)

    def test_deploy_safe(self):
        safe_creation = self.create_test_safe_in_db()
        safe, deployer, payment = safe_creation.safe.address, safe_creation.deployer, safe_creation.payment

        self.send_ether(to=safe, value=payment)

        fund_deployer_task.delay(safe).get()

        safe_funding = SafeFunding.objects.get(safe=safe)

        self.assertTrue(safe_funding.deployer_funded)
        self.assertTrue(safe_funding.safe_funded)
        self.assertFalse(safe_funding.safe_deployed)
        self.assertIsNone(safe_funding.safe_deployed_tx_hash)

        # Safe code is not deployed
        self.assertEqual(self.w3.eth.getCode(safe), b'')

        # This task will check safes with deployer funded and confirmed and send safe raw contract creation tx
        deploy_safes_task.delay().get()

        safe_funding.refresh_from_db()
        self.assertTrue(safe_funding.safe_deployed_tx_hash)
        self.assertFalse(safe_funding.safe_deployed)

        # This time task will check the tx_hash for the safe
        deploy_safes_task.delay().get()

        safe_funding.refresh_from_db()
        self.assertTrue(safe_funding.safe_deployed_tx_hash)
        self.assertTrue(safe_funding.safe_deployed)

        # Safe code is deployed
        self.assertTrue(len(self.w3.eth.getCode(safe)) > 10)

        # Nothing happens if safe is funded
        fund_deployer_task.delay(safe).get()

        # Check deployer tx is checked again
        old_deployer_tx_hash = safe_funding.deployer_funded_tx_hash
        safe_funding.deployer_funded = False
        safe_funding.save()
        fund_deployer_task.delay(safe).get()

        safe_funding.refresh_from_db()
        self.assertEqual(old_deployer_tx_hash, safe_funding.deployer_funded_tx_hash)
        self.assertTrue(safe_funding.deployer_funded)

    def test_safe_with_no_funds(self):
        safe_creation = self.create_test_safe_in_db()
        safe, deployer, payment = safe_creation.safe.address, safe_creation.deployer, safe_creation.payment

        self.assertEqual(self.ethereum_client.get_balance(deployer), 0)
        # No ether is sent to the deployer is safe is empty
        fund_deployer_task.delay(safe, retry=False).get()
        self.assertEqual(self.ethereum_client.get_balance(deployer), 0)

        # No ether is sent to the deployer is safe has less balance than needed
        self.send_ether(to=safe, value=payment - 1)
        fund_deployer_task.delay(safe, retry=False).get()
        self.assertEqual(self.ethereum_client.get_balance(deployer), 0)

    def test_check_deployer_funded(self):
        safe_creation = self.create_test_safe_in_db()
        safe, deployer, payment = safe_creation.safe.address, safe_creation.deployer, safe_creation.payment

        safe_contract = SafeContract.objects.get(address=safe)
        safe_funding = SafeFunding.objects.create(safe=safe_contract)

        safe_funding.safe_funded = True
        safe_funding.deployer_funded_tx_hash = self.w3.sha3(0).hex()
        safe_funding.save()

        # If tx hash is not found should be deleted from database
        check_deployer_funded_task.delay(safe, retry=False).get()

        safe_funding.refresh_from_db()
        self.assertFalse(safe_funding.deployer_funded_tx_hash)

    def test_reorg_before_safe_deploy(self):
        safe_creation = self.create_test_safe_in_db()
        safe, deployer, payment = safe_creation.safe.address, safe_creation.deployer, safe_creation.payment

        self.send_ether(to=safe, value=payment)

        fund_deployer_task.delay(safe).get()
        check_deployer_funded_task.delay(safe).get()

        safe_funding = SafeFunding.objects.get(safe=safe)

        self.assertTrue(safe_funding.safe_funded)
        self.assertTrue(safe_funding.deployer_funded_tx_hash)
        self.assertTrue(safe_funding.deployer_funded)
        self.assertFalse(safe_funding.safe_deployed)

        # Set invalid tx_hash for deployer funding tx
        safe_funding.deployer_funded_tx_hash = self.w3.sha3(0).hex()
        safe_funding.save()

        deploy_safes_task.delay(retry=False).get()

        safe_funding.refresh_from_db()

        # Safe is deployed even if deployer tx is not valid, if balance is found
        self.assertTrue(safe_funding.safe_funded)
        self.assertTrue(safe_funding.deployer_funded_tx_hash)
        self.assertTrue(safe_funding.deployer_funded)
        self.assertTrue(safe_funding.safe_deployed_tx_hash)
        self.assertFalse(safe_funding.safe_deployed)

        # Try to deploy safe with no balance and invalid tx-hash. It will not be deployed and
        # `deployer_funded` will be set to `False` and `deployer_funded_tx_hash` to `None`
        safe_creation = SafeCreationFactory()
        safe_funding = SafeFundingFactory(safe=safe_creation.safe,
                                          safe_funded=True,
                                          deployer_funded=True,
                                          deployer_funded_tx_hash=self.w3.sha3(1).hex())

        self.assertTrue(safe_funding.safe_funded)
        self.assertTrue(safe_funding.deployer_funded)
        self.assertTrue(safe_funding.deployer_funded_tx_hash)
        self.assertFalse(safe_funding.safe_deployed_tx_hash)
        self.assertFalse(safe_funding.safe_deployed)

        deploy_safes_task.delay(retry=False).get()
        safe_funding.refresh_from_db()
        self.assertTrue(safe_funding.safe_funded)
        self.assertFalse(safe_funding.deployer_funded)
        self.assertFalse(safe_funding.deployer_funded_tx_hash)
        self.assertFalse(safe_funding.safe_deployed_tx_hash)
        self.assertFalse(safe_funding.safe_deployed)

    def test_reorg_after_safe_deployed(self):
        safe_creation = self.create_test_safe_in_db()
        safe, deployer, payment = safe_creation.safe.address, safe_creation.deployer, safe_creation.payment

        self.send_ether(to=safe, value=payment)

        fund_deployer_task.delay(safe).get()
        check_deployer_funded_task.delay(safe).get()
        deploy_safes_task.delay().get()

        safe_funding = SafeFunding.objects.get(safe=safe)

        self.assertTrue(safe_funding.safe_deployed_tx_hash)
        self.assertFalse(safe_funding.safe_deployed)

        # Set an invalid tx
        safe_funding.safe_deployed_tx_hash = self.w3.sha3(0).hex()
        safe_funding.save()

        # If tx is not found before 10 minutes, nothing should happen
        deploy_safes_task.delay().get()

        safe_funding.refresh_from_db()
        self.assertTrue(safe_funding.safe_deployed_tx_hash)
        self.assertFalse(safe_funding.safe_deployed)

        # If tx is not found after 10 minutes, safe will be marked to deploy again
        SafeFunding.objects.update(modified=timezone.now() - timedelta(minutes=11))
        deploy_safes_task.delay().get()

        safe_funding.refresh_from_db()
        self.assertFalse(safe_funding.safe_deployed_tx_hash)
        self.assertFalse(safe_funding.safe_deployed)

        # No error when trying to deploy again the contract
        deploy_safes_task.delay().get()

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

    def test_find_internal_txs_task(self):
        ethereum_client_mock = EthereumClientMock()
        internal_tx_service = InternalTxServiceProvider()
        internal_tx_service.ethereum_client = ethereum_client_mock
        self.assertEqual(find_internal_txs_task.delay().get(), 0)

        safe_funding = SafeFundingFactory(safe_deployed=True)
        self.assertEqual(find_internal_txs_task.delay().get(), 0)
        SafeTxStatusFactory(safe=safe_funding.safe)
        self.assertEqual(find_internal_txs_task.delay().get(), 1)

        safe_creation_2 = SafeCreation2Factory(block_number=10)
        self.assertEqual(find_internal_txs_task.delay().get(), 0)
        SafeTxStatusFactory(safe=safe_creation_2.safe)
        self.assertEqual(find_internal_txs_task.delay().get(), 1)

        safe_funding = SafeFundingFactory(safe_deployed=True)
        safe_creation_2 = SafeCreation2Factory(block_number=10)
        SafeTxStatusFactory(safe=safe_funding.safe)
        SafeTxStatusFactory(safe=safe_creation_2.safe)
        self.assertEqual(find_internal_txs_task.delay().get(), 2)
        self.assertEqual(find_internal_txs_task.delay().get(), 0)
        InternalTxServiceProvider.del_singleton()
