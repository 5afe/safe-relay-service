import logging

from django.conf import settings
from django.test import TestCase
from web3 import HTTPProvider, Web3

from ..models import SafeFunding, SafeContract
from ..tasks import deploy_safes_task, fund_deployer_task, send_eth_to, check_deployer_funded_task
from .factories import generate_safe

logger = logging.getLogger(__name__)

GAS_PRICE = settings.SAFE_GAS_PRICE


class TestTasks(TestCase):

    @staticmethod
    def _get_web3_provider():
        return Web3(HTTPProvider(settings.ETHEREUM_NODE_URL))

    @classmethod
    def setUpTestData(cls):
        w3 = cls._get_web3_provider()
        cls.w3 = w3

    def test_balance_in_deployer(self):
        w3 = self.w3
        safe, deployer, payment = generate_safe()

        send_eth_to(w3,
                    to=safe,
                    gas_price=GAS_PRICE,
                    value=payment)

        # If deployer has balance already no ether is sent to the account
        deployer_payment = 1
        send_eth_to(w3,
                    to=deployer,
                    gas_price=GAS_PRICE,
                    value=deployer_payment)

        self.assertEqual(w3.eth.getBalance(deployer), deployer_payment)

        fund_deployer_task.delay(safe, deployer, payment, retry=False).get()

        self.assertEqual(w3.eth.getBalance(deployer), deployer_payment)

    def test_deploy_safe(self):
        w3 = self.w3
        safe, deployer, payment = generate_safe()

        send_eth_to(w3,
                    to=safe,
                    gas_price=GAS_PRICE,
                    value=payment)

        fund_deployer_task.delay(safe, deployer, payment).get()

        safe_funding = SafeFunding.objects.get(safe=safe)

        self.assertTrue(safe_funding.deployer_funded)
        self.assertTrue(safe_funding.safe_funded)
        self.assertFalse(safe_funding.safe_deployed)
        self.assertTrue('' == safe_funding.safe_deployed_tx_hash)

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
        fund_deployer_task.delay(safe, deployer, payment).get()

        # Check deployer tx is checked again
        old_deployer_tx_hash = safe_funding.deployer_funded_tx_hash
        safe_funding.deployer_funded = False
        safe_funding.save()
        fund_deployer_task.delay(safe, deployer, payment).get()

        safe_funding.refresh_from_db()
        self.assertEqual(old_deployer_tx_hash, safe_funding.deployer_funded_tx_hash)
        self.assertTrue(safe_funding.deployer_funded)

    def test_safe_with_no_funds(self):
        w3 = self.w3
        safe, deployer, payment = generate_safe()

        self.assertEqual(w3.eth.getBalance(deployer), 0)
        # No ether is sent to the deployer is safe is empty
        fund_deployer_task.delay(safe, deployer, payment, retry=False).get()
        self.assertEqual(w3.eth.getBalance(deployer), 0)

        # No ether is sent to the deployer is safe has less balance than needed
        send_eth_to(w3,
                    to=safe,
                    gas_price=GAS_PRICE,
                    value=payment - 1)
        fund_deployer_task.delay(safe, deployer, payment, retry=False).get()
        self.assertEqual(w3.eth.getBalance(deployer), 0)

    def test_check_deployer_funded(self):
        w3 = self.w3
        safe, deployer, payment = generate_safe()

        safe_contract = SafeContract.objects.get(address=safe)
        safe_funding = SafeFunding.objects.create(safe=safe_contract)

        safe_funding.safe_funded = True
        safe_funding.deployer_funded_tx_hash = w3.sha3(0).hex()[2:]
        safe_funding.save()

        # If tx hash is not found should be deleted from database
        check_deployer_funded_task.delay(safe, retry=False).get()

        safe_funding.refresh_from_db()
        self.assertFalse(safe_funding.deployer_funded_tx_hash)

    def test_reorg_before_safe_deploy(self):
        # Test safe is not deployed if deployer tx is not valid
        pass

    def test_reorg_after_safe_deployed(self):
        pass

