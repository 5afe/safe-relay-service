import datetime
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from eth_account import Account
from hexbytes import HexBytes
from pytz import utc

from gnosis.eth.constants import NULL_ADDRESS

from ..models import EthereumEvent, SafeContract, SafeFunding, SafeMultisigTx
from .factories import (
    EthereumEventFactory,
    EthereumTxFactory,
    SafeContractFactory,
    SafeCreation2Factory,
    SafeFundingFactory,
    SafeMultisigTxFactory,
)


class TestSafeContractModel(TestCase):
    def test_hex_field(self):
        safe_address = Account.create().address
        safe = SafeContract.objects.create(address=safe_address)
        safe_funding = SafeFunding.objects.create(safe=safe)
        safe_funding.deployer_funded_tx_hash = HexBytes("0xabcd")
        safe_funding.save()
        safe_funding.refresh_from_db()
        self.assertEqual(safe_funding.deployer_funded_tx_hash, "0xabcd")

        safe_funding.deployer_funded_tx_hash = bytes.fromhex("abcd")
        safe_funding.save()
        safe_funding.refresh_from_db()
        self.assertEqual(safe_funding.deployer_funded_tx_hash, "0xabcd")

        safe_funding.deployer_funded_tx_hash = "0xabcd"
        safe_funding.save()
        safe_funding.refresh_from_db()
        self.assertEqual(safe_funding.deployer_funded_tx_hash, "0xabcd")

        safe_funding.deployer_funded_tx_hash = "abcd"
        safe_funding.save()
        safe_funding.refresh_from_db()
        self.assertEqual(safe_funding.deployer_funded_tx_hash, "0xabcd")

        safe_funding.deployer_funded_tx_hash = ""
        safe_funding.save()
        safe_funding.refresh_from_db()
        self.assertEqual(safe_funding.deployer_funded_tx_hash, "0x")

        safe_funding.deployer_funded_tx_hash = None
        safe_funding.save()
        safe_funding.refresh_from_db()
        self.assertIsNone(safe_funding.deployer_funded_tx_hash)

    def test_safe_contract_deployed(self):
        self.assertEqual(SafeContract.objects.deployed().count(), 0)

        safe_funding = SafeFundingFactory(safe_deployed=True)
        self.assertEqual(SafeContract.objects.deployed().count(), 1)
        self.assertEqual(
            SafeContract.objects.deployed()[0].address, safe_funding.safe.address
        )

        safe_creation_2 = SafeCreation2Factory(block_number=2)
        self.assertEqual(SafeContract.objects.deployed().count(), 2)
        self.assertIn(
            safe_creation_2.safe.address,
            [s.address for s in SafeContract.objects.deployed()],
        )

    def test_get_average_deploy_time_total(self):
        from_date = datetime.datetime(2018, 1, 1, tzinfo=utc)
        to_date = timezone.now()
        self.assertIsNone(
            SafeContract.objects.get_average_deploy_time_total(from_date, to_date)
        )
        ethereum_tx = EthereumTxFactory()
        self.assertIsNone(
            SafeContract.objects.get_average_deploy_time_total(from_date, to_date)
        )
        interval = datetime.timedelta(seconds=10)
        safe_creation = SafeCreation2Factory(
            created=ethereum_tx.block.timestamp - interval, tx_hash=ethereum_tx.tx_hash
        )
        from_date = safe_creation.created - interval
        to_date = safe_creation.created + interval
        self.assertEqual(
            SafeContract.objects.get_average_deploy_time_total(from_date, to_date),
            interval,
        )


class TestEthereumEventModel(TestCase):
    def test_ethereum_event(self):
        self.assertEqual(EthereumEvent.objects.count(), 0)

        # Create ERC20 Event
        EthereumEventFactory()
        self.assertEqual(EthereumEvent.objects.count(), 1)
        self.assertEqual(EthereumEvent.objects.erc20_events().count(), 1)
        self.assertEqual(EthereumEvent.objects.erc721_events().count(), 0)

        # Create ERC721 Event
        EthereumEventFactory(
            arguments={"to": NULL_ADDRESS, "from": NULL_ADDRESS, "tokenId": 2}
        )
        self.assertTrue(EthereumEvent.objects.erc20_events().get().is_erc20())
        self.assertTrue(EthereumEvent.objects.erc721_events().get().is_erc721())


class TestSafeMultisigTxModel(TestCase):
    def test_ethereum_tx_hex(self):
        multisig_tx = SafeMultisigTxFactory()
        self.assertIsInstance(multisig_tx.ethereum_tx_id, HexBytes)
        multisig_tx.clean_fields()
        self.assertIsInstance(multisig_tx.ethereum_tx_id, str)

    def test_ethereum_tx_signers(self):
        multisig_tx = SafeMultisigTxFactory(
            signatures=HexBytes(
                "0x09aa550ba80c2b74f57649883e20f78b9bbfd914f729cb5638bc75617b2412392f96cd7e864263e623a9342535a67d8dbd7596a3c85d70c924c43f06ddd0cce51b0000000000000000000000004b7b1cbbd739a2a0e95b32b64fd3d249c671bd44000000000000000000000000000000000000000000000000000000000000000001"
            )
        )
        self.assertEqual(len(multisig_tx.signers()), 2)

    def test_get_last_nonce_for_safe(self):
        safe_address = Account.create().address
        self.assertIsNone(SafeMultisigTx.objects.get_last_nonce_for_safe(safe_address))
        safe_contract = SafeContractFactory(address=safe_address)
        SafeMultisigTxFactory(safe=safe_contract, nonce=0)
        SafeMultisigTxFactory(safe=safe_contract, nonce=0)
        self.assertEqual(
            SafeMultisigTx.objects.get_last_nonce_for_safe(safe_address), 0
        )
        SafeMultisigTxFactory(safe=safe_contract, nonce=1)
        self.assertEqual(
            SafeMultisigTx.objects.get_last_nonce_for_safe(safe_address), 1
        )
        SafeMultisigTxFactory(safe=safe_contract, nonce=2, ethereum_tx__status=1)
        self.assertEqual(
            SafeMultisigTx.objects.get_last_nonce_for_safe(safe_address), 2
        )
        SafeMultisigTxFactory(safe=safe_contract, nonce=3, ethereum_tx__status=0)
        SafeMultisigTxFactory(safe=safe_contract, nonce=3, ethereum_tx__status=2)
        self.assertEqual(
            SafeMultisigTx.objects.get_last_nonce_for_safe(safe_address), 2
        )
        SafeMultisigTxFactory(safe=safe_contract, nonce=3, ethereum_tx__status=None)
        self.assertEqual(
            SafeMultisigTx.objects.get_last_nonce_for_safe(safe_address), 3
        )
        SafeMultisigTxFactory(safe=safe_contract, nonce=8, ethereum_tx__status=None)
        self.assertEqual(
            SafeMultisigTx.objects.get_last_nonce_for_safe(safe_address), 8
        )
        SafeMultisigTxFactory(safe=safe_contract, nonce=16, ethereum_tx__status=2)
        self.assertEqual(
            SafeMultisigTx.objects.get_last_nonce_for_safe(safe_address), 8
        )
        SafeMultisigTxFactory(safe=safe_contract, nonce=16, ethereum_tx__status=1)
        self.assertEqual(
            SafeMultisigTx.objects.get_last_nonce_for_safe(safe_address), 16
        )

    def test_failed(self):
        SafeMultisigTxFactory(ethereum_tx__status=None)
        SafeMultisigTxFactory(ethereum_tx__status=1)
        self.assertEqual(SafeMultisigTx.objects.failed().count(), 0)
        SafeMultisigTxFactory(ethereum_tx__status=0)
        SafeMultisigTxFactory(ethereum_tx__status=8)
        self.assertEqual(SafeMultisigTx.objects.failed().count(), 2)

    def test_not_failed(self):
        SafeMultisigTxFactory(ethereum_tx__status=None)
        self.assertEqual(SafeMultisigTx.objects.not_failed().count(), 1)
        SafeMultisigTxFactory(ethereum_tx__status=1)
        self.assertEqual(SafeMultisigTx.objects.not_failed().count(), 2)
        SafeMultisigTxFactory(ethereum_tx__status=0)
        SafeMultisigTxFactory(ethereum_tx__status=8)
        self.assertEqual(SafeMultisigTx.objects.not_failed().count(), 2)

    def test_pending(self):
        self.assertFalse(SafeMultisigTx.objects.pending(0))

        SafeMultisigTxFactory(created=timezone.now())
        self.assertFalse(SafeMultisigTx.objects.pending(0))

        SafeMultisigTxFactory(created=timezone.now(), ethereum_tx__block=None)
        self.assertEqual(SafeMultisigTx.objects.pending(0).count(), 1)
        self.assertFalse(SafeMultisigTx.objects.pending(30))

        SafeMultisigTxFactory(
            created=timezone.now() - timedelta(seconds=60), ethereum_tx__block=None
        )
        self.assertEqual(SafeMultisigTx.objects.pending(30).count(), 1)
        SafeMultisigTxFactory(
            created=timezone.now() - timedelta(minutes=60), ethereum_tx__block=None
        )
        self.assertEqual(SafeMultisigTx.objects.pending(30).count(), 2)

    def test_successful(self):
        SafeMultisigTxFactory(ethereum_tx__status=None)
        SafeMultisigTxFactory(ethereum_tx__status=1)
        self.assertEqual(SafeMultisigTx.objects.successful().count(), 1)
        SafeMultisigTxFactory(ethereum_tx__status=0)
        SafeMultisigTxFactory(ethereum_tx__status=8)
        self.assertEqual(SafeMultisigTx.objects.successful().count(), 1)
        SafeMultisigTxFactory(ethereum_tx__status=1)
        self.assertEqual(SafeMultisigTx.objects.successful().count(), 2)

    def test_get_average_execution_time(self):
        from_date = datetime.datetime(2018, 1, 1, tzinfo=utc)
        to_date = timezone.now()
        self.assertIsNone(
            SafeMultisigTx.objects.get_average_execution_time(from_date, to_date)
        )
        safe_multisig_tx = SafeMultisigTxFactory()
        interval = datetime.timedelta(seconds=10)
        safe_multisig_tx.ethereum_tx.block.timestamp = (
            safe_multisig_tx.created + interval
        )
        safe_multisig_tx.ethereum_tx.block.save()
        from_date = safe_multisig_tx.created - interval
        to_date = safe_multisig_tx.created + interval
        self.assertEqual(
            SafeMultisigTx.objects.get_average_execution_time(from_date, to_date),
            interval,
        )
        safe_multisig_tx_2 = SafeMultisigTxFactory()
        interval_2 = datetime.timedelta(seconds=5)
        safe_multisig_tx_2.ethereum_tx.block.timestamp = (
            safe_multisig_tx_2.created + interval_2
        )
        safe_multisig_tx_2.ethereum_tx.block.save()
        self.assertEqual(
            SafeMultisigTx.objects.get_average_execution_time(from_date, to_date),
            (interval + interval_2) / 2,
        )
