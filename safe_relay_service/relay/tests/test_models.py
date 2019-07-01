from datetime import timedelta

from django.test import TestCase

from eth_account import Account
from hexbytes import HexBytes
from web3 import Web3

from gnosis.eth.constants import NULL_ADDRESS

from ..models import (EthereumEvent, EthereumTxCallType, InternalTx,
                      SafeContract, SafeFunding, SafeMultisigTx)
from .factories import (EthereumEventFactory, InternalTxFactory,
                        SafeCreation2Factory, SafeFundingFactory, SafeMultisigTxFactory)


class TestSafeContractModel(TestCase):
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


class TestEthereumEventModel(TestCase):
    def test_ethereum_event(self):
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


class TestInternalTxModel(TestCase):
    def test_internal_tx_balance(self):
        address = Account.create().address
        value = Web3.toWei(1, 'ether')

        # TODO Fix this bug
        # It will be 0, it needs at least one `ingoing` and one `outgoing` tx
        InternalTxFactory(to=address, value=value)
        self.assertEqual(InternalTx.objects.calculate_balance(address), 0)

        InternalTxFactory(_from=address, value=0)
        self.assertEqual(InternalTx.objects.calculate_balance(address), value)

        InternalTxFactory(_from=address, value=value - 1)
        self.assertEqual(InternalTx.objects.calculate_balance(address), 1)

        # Delegate CALLs are ignored
        InternalTxFactory(_from=address, value=1, call_type=EthereumTxCallType.DELEGATE_CALL.value)
        self.assertEqual(InternalTx.objects.calculate_balance(address), 1)

        # Txs to itself are ignored
        InternalTxFactory(_from=address, to=address, value=1)
        self.assertEqual(InternalTx.objects.calculate_balance(address), 1)

        # More income
        InternalTxFactory(to=address, value=1)
        self.assertEqual(InternalTx.objects.calculate_balance(address), 2)


class TestSafeMultisigTxModel(TestCase):
    def test_get_average_execution_time(self):
        self.assertIsNone(SafeMultisigTx.objects.get_average_execution_time())
        safe_multisig_tx = SafeMultisigTxFactory()
        interval = timedelta(seconds=10)
        safe_multisig_tx.ethereum_tx.block.timestamp = safe_multisig_tx.created + interval
        safe_multisig_tx.ethereum_tx.block.save()
        self.assertEqual(SafeMultisigTx.objects.get_average_execution_time(), interval)
        safe_multisig_tx_2 = SafeMultisigTxFactory()
        interval_2 = timedelta(seconds=5)
        safe_multisig_tx_2.ethereum_tx.block.timestamp = safe_multisig_tx_2.created + interval_2
        safe_multisig_tx_2.ethereum_tx.block.save()
        self.assertEqual(SafeMultisigTx.objects.get_average_execution_time(), (interval + interval_2) / 2)
