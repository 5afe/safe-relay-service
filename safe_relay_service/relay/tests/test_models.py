import logging

from django.conf import settings
from django.test import TestCase

from hexbytes import HexBytes

from ..models import SafeFunding
from .utils import generate_safe

logger = logging.getLogger(__name__)

LOG_TITLE_WIDTH = 100

GAS_PRICE = settings.SAFE_GAS_PRICE


class TestModels(TestCase):
    def test_hex_field(self):
        safe = generate_safe().safe
        safe_funding = SafeFunding.objects.create(safe=safe)
        safe_funding.deployer_funded_tx_hash = HexBytes('0xabcd')
        safe_funding.save()
        safe_funding.refresh_from_db()
        self.assertEqual(safe_funding.deployer_funded_tx_hash, '0xabcd')

        safe_funding.deployer_funded_tx_hash = bytes.fromhex('abcd')
        safe_funding.save()
        safe_funding.refresh_from_db()
        self.assertEqual(safe_funding.deployer_funded_tx_hash, '0xabcd')

        safe_funding.deployer_funded_tx_hash = '0xabcd'
        safe_funding.save()
        safe_funding.refresh_from_db()
        self.assertEqual(safe_funding.deployer_funded_tx_hash, '0xabcd')

        safe_funding.deployer_funded_tx_hash = 'abcd'
        safe_funding.save()
        safe_funding.refresh_from_db()
        self.assertEqual(safe_funding.deployer_funded_tx_hash, '0xabcd')

        safe_funding.deployer_funded_tx_hash = ''
        safe_funding.save()
        safe_funding.refresh_from_db()
        self.assertEqual(safe_funding.deployer_funded_tx_hash, '0x')

        safe_funding.deployer_funded_tx_hash = None
        safe_funding.save()
        safe_funding.refresh_from_db()
        self.assertIsNone(safe_funding.deployer_funded_tx_hash)
