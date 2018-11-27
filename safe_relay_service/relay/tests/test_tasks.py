import logging
from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from gnosis.safe.ethereum_service import EthereumServiceProvider

from ..models import SafeContract, SafeFunding
from ..tasks import (check_deployer_funded_task, deploy_safes_task,
                     fund_deployer_task)
from .factories import SafeCreationFactory, SafeFundingFactory
from .utils import generate_safe

logger = logging.getLogger(__name__)

GAS_PRICE = settings.SAFE_GAS_PRICE


class TestTasks(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.ethereum_service = EthereumServiceProvider()
        cls.w3 = cls.ethereum_service.w3

    def test_balance_in_deployer(self):
        safe_creation = generate_safe()
        safe, deployer, payment = safe_creation.safe.address, safe_creation.deployer, safe_creation.payment

        self.ethereum_service.send_eth_to(
            to=safe,
            gas_price=GAS_PRICE,
            value=payment)

        # If deployer has balance already no ether is sent to the account
        deployer_payment = 1
        self.ethereum_service.send_eth_to(
            to=deployer,
            gas_price=GAS_PRICE,
            value=deployer_payment)

        self.assertEqual(self.ethereum_service.get_balance(deployer), deployer_payment)

        fund_deployer_task.delay(safe, retry=False).get()

        self.assertEqual(self.ethereum_service.get_balance(deployer), deployer_payment)

    def test_deploy_safe(self):
        safe_creation = generate_safe()
        safe, deployer, payment = safe_creation.safe.address, safe_creation.deployer, safe_creation.payment

        self.ethereum_service.send_eth_to(
            to=safe,
            gas_price=GAS_PRICE,
            value=payment)

        fund_deployer_task.delay(safe).get()

        safe_funding = SafeFunding.objects.get(safe=safe)

        self.assertTrue(safe_funding.deployer_funded)
        self.assertTrue(safe_funding.safe_funded)
        self.assertFalse(safe_funding.safe_deployed)
        self.assertIsNone(safe_funding.safe_deployed_tx_hash)

        # Safe code is not deployed
        self.assertEqual(self.w3.eth.getCode(safe), b'\x00')

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
        safe_creation = generate_safe()
        safe, deployer, payment = safe_creation.safe.address, safe_creation.deployer, safe_creation.payment

        self.assertEqual(self.ethereum_service.get_balance(deployer), 0)
        # No ether is sent to the deployer is safe is empty
        fund_deployer_task.delay(safe, retry=False).get()
        self.assertEqual(self.ethereum_service.get_balance(deployer), 0)

        # No ether is sent to the deployer is safe has less balance than needed
        self.ethereum_service.send_eth_to(
            to=safe,
            gas_price=GAS_PRICE,
            value=payment - 1)
        fund_deployer_task.delay(safe, retry=False).get()
        self.assertEqual(self.ethereum_service.get_balance(deployer), 0)

    def test_check_deployer_funded(self):
        safe_creation = generate_safe()
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
        safe_creation = generate_safe()
        safe, deployer, payment = safe_creation.safe.address, safe_creation.deployer, safe_creation.payment

        self.ethereum_service.send_eth_to(
            to=safe,
            gas_price=GAS_PRICE,
            value=payment)

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
        safe_creation = generate_safe()
        safe, deployer, payment = safe_creation.safe.address, safe_creation.deployer, safe_creation.payment

        self.ethereum_service.send_eth_to(
            to=safe,
            gas_price=GAS_PRICE,
            value=payment)

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
