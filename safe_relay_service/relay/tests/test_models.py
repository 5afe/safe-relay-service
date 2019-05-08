from django.test import TestCase

from eth_account import Account
from hexbytes import HexBytes

from gnosis.eth.constants import NULL_ADDRESS

from ..models import EthereumEvent, SafeContract, SafeFunding
from .factories import (EthereumEventFactory, SafeCreation2Factory,
                        SafeFundingFactory)


class TestModels(TestCase):
    def test_hex_field(self):
        safe_address = Account.create().address
        safe = SafeContract.objects.create(address=safe_address)
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

    def test_safe_contract_deployed(self):
        self.assertEqual(SafeContract.objects.deployed().count(), 0)

        safe_funding = SafeFundingFactory(safe_deployed=True)
        self.assertEqual(SafeContract.objects.deployed().count(), 1)
        self.assertEqual(SafeContract.objects.deployed()[0].address, safe_funding.safe.address)

        safe_creation_2 = SafeCreation2Factory(block_number=2)
        self.assertEqual(SafeContract.objects.deployed().count(), 2)
        self.assertIn(safe_creation_2.safe.address, [s.address for s in SafeContract.objects.deployed()])

    def test_ethereum_event_model(self):
        self.assertEqual(EthereumEvent.objects.count(), 0)

        # Create ERC20 Event
        EthereumEventFactory()
        self.assertEqual(EthereumEvent.objects.count(), 1)
        self.assertEqual(EthereumEvent.objects.erc20_events().count(), 1)
        self.assertEqual(EthereumEvent.objects.erc721_events().count(), 0)

        # Create ERC721 Event
        EthereumEventFactory(arguments={'to': NULL_ADDRESS,
                                        'from': NULL_ADDRESS,
                                        'tokenId': 2})
        self.assertTrue(EthereumEvent.objects.erc20_events().get().is_erc20())
        self.assertTrue(EthereumEvent.objects.erc721_events().get().is_erc721())
