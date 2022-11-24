import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin

from django.core.management.base import BaseCommand
from django.urls import reverse

import requests
from eth_account import Account
from web3 import Web3

from gnosis.eth import EthereumClient
from gnosis.safe import SafeTx
from gnosis.safe.tests.utils import generate_valid_s


class Command(BaseCommand):
    base_url: str
    w3: Web3
    ethereum_client: EthereumClient
    main_account: Account
    main_account_nonce: int

    help = (
        "Do a basic testing of a deployed safe relay service "
        "You need to provide a valid account for the net you are testing"
    )

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument(
            "base_url", help="Base url of relay (e.g. http://safe-relay.gnosistest.com)"
        )
        parser.add_argument("private_key", help="Private key")
        parser.add_argument(
            "--node-url",
            default="http://localhost:8545",
            help="Ethereum node in the same net that the relay",
        )
        parser.add_argument(
            "--payment-token", help="Use payment token for creating/testing"
        )
        parser.add_argument(
            "--v2",
            help="Use v2 endpoints for safe V1.0.0 creation. By default V1.1.1 will be used",
            action="store_true",
            default=False,
        )
        parser.add_argument(
            "--multiple-txs",
            help="Test sending multiple txs at the same time",
            action="store_true",
            default=False,
        )

    def get_safe_url(self, address):
        return urljoin(self.base_url, reverse("v1:safe", kwargs={"address": address}))

    def get_estimate_url(self, address):
        return urljoin(
            self.base_url,
            reverse("v1:safe-multisig-tx-estimate", kwargs={"address": address}),
        )

    def get_tx_url(self, address):
        return urljoin(
            self.base_url, reverse("v1:safe-multisig-txs", kwargs={"address": address})
        )

    def get_signal_url(self, address):
        return urljoin(
            self.base_url, reverse("v1:safe-signal", kwargs={"address": address})
        )

    def handle(self, *args, **options):
        self.base_url = options["base_url"]
        v2 = options["v2"]
        payment_token = options["payment_token"]
        multiple_txs = options["multiple_txs"]

        self.ethereum_client = EthereumClient(options["node_url"])
        self.w3 = self.ethereum_client.w3
        self.main_account = Account.from_key(options["private_key"])
        self.main_account_nonce = self.w3.eth.getTransactionCount(
            self.main_account.address, "pending"
        )
        main_account_balance = self.w3.eth.get_balance(self.main_account.address)
        main_account_balance_eth = self.w3.fromWei(main_account_balance, "ether")
        self.stdout.write(
            self.style.SUCCESS(
                f"Using {self.main_account.address} as main account with "
                f"balance={main_account_balance_eth}"
            )
        )
        about_url = urljoin(self.base_url, reverse("v1:about"))
        about_json = requests.get(about_url).json()

        if v2:
            master_copy_address = about_json["settings"]["SAFE_V1_0_0_CONTRACT_ADDRESS"]
        else:
            master_copy_address = about_json["settings"]["SAFE_CONTRACT_ADDRESS"]
        self.stdout.write(
            self.style.SUCCESS(f"Using master-copy={master_copy_address}")
        )

        accounts = [Account.create() for _ in range(3)]
        for account in accounts:
            self.stdout.write(
                self.style.SUCCESS(
                    "Created account=%s with key=%s"
                    % (account.address, account.key.hex())
                )
            )
        accounts.append(self.main_account)
        accounts.sort(key=lambda acc: acc.address.lower())
        owners = [account.address for account in accounts]

        if multiple_txs:
            safe_addresses = []
            self.stdout.write(self.style.SUCCESS("Creating multiple safes"))
            for _ in range(10):
                safe_address, payment = self.create_safe(
                    owners, threshold=2, payment_token=payment_token, v2=v2
                )
                self.fund_safe(
                    safe_address, payment, payment_token, wait_for_receipt=False
                )
                safe_addresses.append(safe_address)

            safe_versions = []
            for safe_address in safe_addresses:
                safe_info = self.check_safe_deployed(
                    safe_address, owners, master_copy_address
                )
                safe_versions.append(safe_info["version"])

            self.stdout.write(
                self.style.SUCCESS("Every safe was deployed and checked. Sending txs")
            )
            tx_hashes = []
            for safe_address, safe_version in zip(safe_addresses, safe_versions):
                tx_hashes.append(
                    self.send_safe_tx(
                        safe_address,
                        safe_version,
                        accounts,
                        payment_token,
                        wait_for_receipt=False,
                    )
                )

            for tx_hash in tx_hashes:
                assert (
                    self.w3.eth.wait_for_transaction_receipt(
                        tx_hash, timeout=500
                    ).status
                    == 1
                ), ("Error on tx-hash=%s" % tx_hash)
            self.stdout.write(self.style.SUCCESS("Success with tx-hash=%s" % tx_hash))
        else:
            safe_address, payment = self.create_safe(
                owners, threshold=2, payment_token=payment_token, v2=v2
            )
            self.fund_safe(safe_address, payment, payment_token)
            safe_info = self.check_safe_deployed(
                safe_address, owners, master_copy_address
            )
            safe_version = safe_info["version"]
            self.send_safe_tx(safe_address, safe_version, accounts, payment_token)

    def create_safe(
        self,
        owners: List[Account],
        threshold: int = 2,
        payment_token: Optional[None] = None,
        v2: bool = False,
    ):
        if v2:
            creation_url = urljoin(self.base_url, reverse("v2:safe-creation"))
        else:
            creation_url = urljoin(self.base_url, reverse("v3:safe-creation"))
        data = {
            "saltNonce": generate_valid_s(),
            "owners": owners,
            "threshold": threshold,
        }
        if payment_token:
            data["paymentToken"] = payment_token
        self.stdout.write(self.style.SUCCESS(f"Calling creation url {creation_url}"))
        r = requests.post(creation_url, json=data)
        assert r.ok, f"Error creating safe {r.content} using url={creation_url}"

        safe_address, payment = r.json()["safe"], int(r.json()["payment"])
        return safe_address, payment

    def fund_safe(
        self,
        safe_address,
        payment,
        payment_token: Optional[None] = None,
        wait_for_receipt: bool = True,
    ):
        self.stdout.write(
            self.style.SUCCESS(
                "Created safe=%s, need payment=%d" % (safe_address, payment)
            )
        )
        if payment_token:
            tx_hash = self.ethereum_client.erc20.send_tokens(
                safe_address,
                int(payment * 1.4),
                payment_token,
                self.main_account.key,
                nonce=self.main_account_nonce,
            )
            self.main_account_nonce += 1
            self.stdout.write(
                self.style.SUCCESS(
                    "Sent payment of payment-token=%s, waiting for "
                    "receipt with tx-hash=%s" % (payment_token, tx_hash.hex())
                )
            )
            self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=500)

        tx_hash = self.ethereum_client.send_eth_to(
            self.main_account.key,
            safe_address,
            self.ethereum_client.w3.eth.gasPrice,
            payment * 2,
            nonce=self.main_account_nonce,
        )
        self.main_account_nonce += 1
        self.stdout.write(
            self.style.SUCCESS(
                f"Sent payment * 2, waiting for receipt with tx-hash={tx_hash.hex()}"
            )
        )
        if wait_for_receipt:
            self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=500)
            self.stdout.write(
                self.style.SUCCESS(
                    "Payment sent and mined. Waiting for safe to be deployed"
                )
            )
        signal_url = self.get_signal_url(safe_address)
        r = requests.put(signal_url)
        assert r.ok, "Error sending signal that safe is funded %s" % r.content
        return safe_address

    def check_safe_deployed(
        self, safe_address, owners, master_copy_address
    ) -> Dict[str, Any]:
        while True:
            if self.w3.eth.getCode(safe_address):
                break
            time.sleep(10)
        # Check safe was created successfully
        self.stdout.write(self.style.SUCCESS(f"Safe={safe_address} was deployed"))
        r = requests.get(self.get_safe_url(safe_address))
        assert r.ok, "Safe deployed is not working"
        safe_info = r.json()
        assert set(safe_info["owners"]) == set(owners)
        assert safe_info["threshold"] == 2
        assert safe_info["nonce"] == 0
        assert safe_info["masterCopy"] == master_copy_address
        self.stdout.write(self.style.SUCCESS(safe_info))

        return safe_info

    def send_safe_tx(
        self,
        safe_address: str,
        safe_version: str,
        accounts: List[Account],
        payment_token: Optional[str] = None,
        wait_for_receipt: bool = True,
    ) -> bytes:
        safe_balance = self.w3.eth.get_balance(safe_address)
        tx = {
            "to": self.main_account.address,
            "value": safe_balance,
            "data": None,
            "operation": 0,  # CALL
            "gasToken": payment_token,
        }

        if payment_token:
            tx["gasToken"] = payment_token

        # We used payment * 2 to fund the safe, now we return ether to the main account
        r = requests.post(self.get_estimate_url(safe_address), json=tx)
        assert r.ok, "Estimate not working %s" % r.content
        self.stdout.write(
            self.style.SUCCESS("Estimation=%s for tx=%s" % (r.json(), tx))
        )
        # estimate_gas = r.json()['safeTxGas'] + r.json()['dataGas'] + r.json()['operationalGas']
        # fees = r.json()['gasPrice'] * estimate_gas

        if payment_token:
            # We can transfer the full amount as we are paying fees with a token
            tx["value"] = safe_balance
        else:
            estimate_gas = (
                r.json()["safeTxGas"] + r.json()["dataGas"] + r.json()["operationalGas"]
            )
            fees = r.json()["gasPrice"] * estimate_gas
            tx["value"] = safe_balance - fees

        tx["dataGas"] = r.json()["dataGas"] + r.json()["operationalGas"]
        tx["gasPrice"] = r.json()["gasPrice"]
        tx["safeTxGas"] = r.json()["safeTxGas"]
        tx["nonce"] = (
            0 if r.json()["lastUsedNonce"] is None else r.json()["lastUsedNonce"] + 1
        )
        tx["refundReceiver"] = None

        # Sign the tx
        safe_tx_hash = SafeTx(
            None,
            safe_address,
            tx["to"],
            tx["value"],
            tx["data"],
            tx["operation"],
            tx["safeTxGas"],
            tx["dataGas"],
            tx["gasPrice"],
            tx["gasToken"],
            tx["refundReceiver"],
            safe_nonce=tx["nonce"],
            safe_version=safe_version,
        ).safe_tx_hash

        signatures = [account.signHash(safe_tx_hash) for account in accounts[:2]]
        curated_signatures = [
            {"r": signature["r"], "s": signature["s"], "v": signature["v"]}
            for signature in signatures
        ]
        tx["signatures"] = curated_signatures

        self.stdout.write(
            self.style.SUCCESS(
                "Sending multisig tx to return some funds to the main owner %s" % tx
            )
        )
        r = requests.post(self.get_tx_url(safe_address), json=tx)
        assert r.ok, "Error sending tx %s" % r.content

        multisig_tx_hash = r.json()["txHash"]
        self.stdout.write(
            self.style.SUCCESS("Tx with tx-hash=%s was successful" % multisig_tx_hash)
        )
        if wait_for_receipt:
            self.w3.eth.wait_for_transaction_receipt(multisig_tx_hash, timeout=500)
        return multisig_tx_hash

    def send_multiple_txs(
        self,
        safe_address: str,
        safe_version: str,
        accounts: List[Account],
        payment_token: Optional[str] = None,
        number_txs: int = 100,
    ) -> List[bytes]:
        tx_hash = self.ethereum_client.send_eth_to(
            self.main_account.key,
            safe_address,
            self.ethereum_client.w3.eth.gasPrice,
            self.w3.toWei(1, "ether"),
            nonce=self.main_account_nonce,
        )
        self.main_account_nonce += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Sent 1 ether for testing sending multiple txs, "
                "waiting for receipt with tx-hash=%s" % tx_hash.hex()
            )
        )
        self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=500)

        self.stdout.write(self.style.SUCCESS("Sending %d txs of 1 wei" % number_txs))
        safe_nonce = None
        tx_hashes = []
        for _ in range(number_txs):
            tx = {
                "to": self.main_account.address,
                "value": 1,  # Send 1 wei
                "data": None,
                "operation": 0,  # CALL
                "gasToken": payment_token,
            }

            if payment_token:
                tx["gasToken"] = payment_token

            # We used payment * 2 to fund the safe, now we return ether to the main account
            r = requests.post(self.get_estimate_url(safe_address), json=tx)
            assert r.ok, "Estimate not working %s" % r.content
            self.stdout.write(
                self.style.SUCCESS("Estimation=%s for tx=%s" % (r.json(), tx))
            )
            # estimate_gas = r.json()['safeTxGas'] + r.json()['dataGas'] + r.json()['operationalGas']
            # fees = r.json()['gasPrice'] * estimate_gas

            tx["dataGas"] = r.json()["dataGas"]
            tx["gasPrice"] = r.json()["gasPrice"]
            tx["safeTxGas"] = r.json()["safeTxGas"]
            if safe_nonce is not None:
                safe_nonce += 1
            else:
                safe_nonce = (
                    0
                    if r.json()["lastUsedNonce"] is None
                    else r.json()["lastUsedNonce"] + 1
                )
            tx["nonce"] = safe_nonce
            tx["refundReceiver"] = None

            # Sign the tx
            safe_tx_hash = SafeTx(
                None,
                safe_address,
                tx["to"],
                tx["value"],
                tx["data"],
                tx["operation"],
                tx["safeTxGas"],
                tx["dataGas"],
                tx["gasPrice"],
                tx["gasToken"],
                tx["refundReceiver"],
                tx["nonce"],
                safe_version=safe_version,
            ).safe_tx_hash

            signatures = [account.signHash(safe_tx_hash) for account in accounts[:2]]
            curated_signatures = [
                {"r": signature["r"], "s": signature["s"], "v": signature["v"]}
                for signature in signatures
            ]
            tx["signatures"] = curated_signatures

            self.stdout.write(
                self.style.SUCCESS("Sending tx to stress test the server %s" % tx)
            )
            r = requests.post(self.get_tx_url(safe_address), json=tx)
            assert r.ok, "Error sending tx %s" % r.content

            tx_hash = r.json()["txHash"]
            tx_hashes.append(tx_hash)

            tx_receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=500)
            assert tx_receipt.status == 1, "Error with tx %s" % tx_hash.hex()

        for tx_hash in tx_hashes:
            tx_receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=500)
            assert tx_receipt.status == 1, "Error with tx %s" % tx_hash.hex()
            self.stdout.write(
                self.style.SUCCESS("Tx with tx-hash=%s was successful" % tx_hash)
            )
        return tx_hashes
