import logging

from django.conf import settings
from django.test import TestCase
from web3 import HTTPProvider, Web3

from ..helpers import create_safe_tx
from ..models import SafeFunding
from ..tasks import deploy_safes_task, fund_deployer_task, send_eth_to
from .factories import generate_valid_s

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

    def test_tasks(self):
        w3 = self.w3
        s = generate_valid_s()
        owners = w3.eth.accounts[2:6]
        threshold = len(owners) - 1

        s = create_safe_tx(s, owners, threshold)
        safe, deployer, payment = s.data['safe'], s.data['tx']['from'], int(s.data['payment'])

        send_eth_to(w3,
                    to=safe,
                    gas_price=GAS_PRICE,
                    value=payment)

        fund_deployer_task.delay(safe, deployer, payment)

        safe_funding = SafeFunding.objects.get(safe=safe)

        self.assertTrue(safe_funding.deployer_funded)
        self.assertTrue(safe_funding.safe_funded)
        self.assertFalse(safe_funding.safe_deployed)
        self.assertTrue('' == safe_funding.safe_deployed_tx_hash)

        # Safe code is not deployed
        self.assertEqual(self.w3.eth.getCode(safe), b'\x00')

        # This task will check safes with deployer funded and confirmed and send safe raw contract creation tx
        deploy_safes_task.delay()

        safe_funding.refresh_from_db()
        self.assertTrue(safe_funding.safe_deployed_tx_hash)
        self.assertFalse(safe_funding.safe_deployed)

        # This time task will check the tx_hash for the safe
        deploy_safes_task.delay()

        safe_funding.refresh_from_db()
        self.assertTrue(safe_funding.safe_deployed_tx_hash)
        self.assertTrue(safe_funding.safe_deployed)

        # Safe code is deployed
        self.assertTrue(len(self.w3.eth.getCode(safe)) > 10)
