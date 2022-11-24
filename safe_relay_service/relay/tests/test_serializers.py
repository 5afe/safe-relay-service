from django.conf import settings
from django.test import TestCase

from eth_account import Account
from faker import Faker
from hexbytes import HexBytes

from gnosis.eth.constants import NULL_ADDRESS
from gnosis.eth.utils import (
    get_eth_address_with_invalid_checksum,
    get_eth_address_with_key,
)
from gnosis.safe.safe_tx import SafeTx

from ..models import SafeContract, SafeFunding
from ..serializers import (
    SafeCreation2Serializer,
    SafeCreationSerializer,
    SafeFundingResponseSerializer,
    SafeRelayMultisigTxSerializer,
)

faker = Faker()


class TestSerializers(TestCase):
    SECPK1N = (
        115792089237316195423570985008687907852837564279074904382605163141518161494337
    )

    def test_safe_creation_serializer(self):
        s = self.SECPK1N // 2
        owners = [Account.create().address for _ in range(3)]
        invalid_checksumed_address = get_eth_address_with_invalid_checksum()

        data = {"s": s, "owners": owners, "threshold": len(owners)}
        self.assertTrue(SafeCreationSerializer(data=data).is_valid())

        data = {"s": s, "owners": owners, "threshold": len(owners) + 1}
        serializer = SafeCreationSerializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "Threshold cannot be greater", str(serializer.errors["non_field_errors"])
        )

        data = {
            "s": s,
            "owners": owners + [invalid_checksumed_address],
            "threshold": len(owners),
        }
        self.assertFalse(SafeCreationSerializer(data=data).is_valid())

        data = {"s": s, "owners": [], "threshold": len(owners)}
        serializer = SafeCreationSerializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_safe_creation2_serializer(self):
        salt_nonce = 5
        owners = [Account.create().address for _ in range(3)]
        invalid_checksumed_address = get_eth_address_with_invalid_checksum()

        data = {"salt_nonce": salt_nonce, "owners": owners, "threshold": len(owners)}
        self.assertTrue(SafeCreation2Serializer(data=data).is_valid())

        data = {
            "salt_nonce": salt_nonce,
            "owners": owners,
            "threshold": len(owners) + 1,
        }
        serializer = SafeCreation2Serializer(data=data)
        self.assertFalse(serializer.is_valid())
        self.assertIn(
            "Threshold cannot be greater", str(serializer.errors["non_field_errors"])
        )

        data = {
            "salt_nonce": salt_nonce,
            "owners": owners + [invalid_checksumed_address],
            "threshold": len(owners),
        }
        self.assertFalse(SafeCreation2Serializer(data=data).is_valid())

        data = {"salt_nonce": salt_nonce, "owners": [], "threshold": len(owners)}
        serializer = SafeCreation2Serializer(data=data)
        self.assertFalse(serializer.is_valid())

    def test_funding_serializer(self):
        owner1, _ = get_eth_address_with_key()
        safe_contract = SafeContract.objects.create(
            address=owner1, master_copy="0x" + "0" * 40
        )
        safe_funding = SafeFunding.objects.create(safe=safe_contract)

        s = SafeFundingResponseSerializer(safe_funding)

        self.assertTrue(s.data)

    def test_safe_multisig_tx_serializer(self):
        safe = get_eth_address_with_key()[0]
        to = None
        value = int(10e18)
        tx_data = None
        operation = 0
        safe_tx_gas = 1
        data_gas = 1
        gas_price = 1
        gas_token = None
        refund_receiver = None
        nonce = 0

        data = {
            "safe": safe,
            "to": to,
            "value": value,  # 1 ether
            "data": tx_data,
            "operation": operation,
            "safe_tx_gas": safe_tx_gas,
            "data_gas": data_gas,
            "gas_price": gas_price,
            "gas_token": gas_token,
            "nonce": nonce,
            "signatures": [{"r": 5, "s": 7, "v": 27}, {"r": 17, "s": 29, "v": 28}],
        }
        serializer = SafeRelayMultisigTxSerializer(data=data)
        self.assertFalse(serializer.is_valid())  # Less signatures than threshold

        # Signatures must be sorted!
        accounts = [Account.create() for _ in range(2)]
        accounts.sort(key=lambda x: x.address.lower())

        safe = get_eth_address_with_key()[0]
        data["safe"] = safe

        serializer = SafeRelayMultisigTxSerializer(data=data)
        self.assertFalse(serializer.is_valid())  # To and data cannot both be null

        tx_data = HexBytes("0xabcd")
        data["data"] = tx_data.hex()
        serializer = SafeRelayMultisigTxSerializer(data=data)
        self.assertFalse(
            serializer.is_valid()
        )  # Operation is not create, but no to provided

        # Now we fix the signatures
        to = accounts[-1].address
        data["to"] = to
        multisig_tx_hash = SafeTx(
            None,
            safe,
            to,
            value,
            tx_data,
            operation,
            safe_tx_gas,
            data_gas,
            gas_price,
            gas_token,
            refund_receiver,
            safe_nonce=nonce,
            safe_version="1.2.0",
        ).safe_tx_hash

        signatures = [account.signHash(multisig_tx_hash) for account in accounts]
        data["signatures"] = [{"v": s.v, "r": s.r, "s": s.s} for s in signatures]
        serializer = SafeRelayMultisigTxSerializer(data=data)
        self.assertTrue(serializer.is_valid())

        data = {
            "safe": safe,
            "to": to,
            "value": value,  # 1 ether
            "data": tx_data,
            "operation": operation,
            "safe_tx_gas": safe_tx_gas,
            "data_gas": data_gas,
            "gas_price": gas_price,
            "gas_token": gas_token,
            "nonce": nonce,
            "refund_receiver": accounts[
                0
            ].address,  # Refund receiver must be empty or relay service sender
            "signatures": [{"r": 5, "s": 7, "v": 27}],
        }
        serializer = SafeRelayMultisigTxSerializer(data=data)
        self.assertFalse(serializer.is_valid())

        data["refund_receiver"] = Account.from_key(
            settings.SAFE_TX_SENDER_PRIVATE_KEY
        ).address
        serializer = SafeRelayMultisigTxSerializer(data=data)
        self.assertTrue(serializer.is_valid())

        data["refund_receiver"] = NULL_ADDRESS
        serializer = SafeRelayMultisigTxSerializer(data=data)
        self.assertTrue(serializer.is_valid())
