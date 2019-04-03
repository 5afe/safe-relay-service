import time
from typing import List, Optional
from urllib.parse import urljoin

from django.core.management.base import BaseCommand
from django.urls import reverse

import requests
from eth_account import Account
from web3 import HTTPProvider, Web3

from gnosis.eth.contracts import get_erc20_contract
from gnosis.safe import SafeService
from gnosis.safe.tests.utils import generate_valid_s


class Command(BaseCommand):
    base_url: str
    w3: Web3
    main_account: Account

    help = 'Do a basic testing of a deployed safe relay service ' \
           'You need to provide a valid account for the net you are testing'

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('base_url', help='Base url of relay (e.g. http://safe-relay.gnosistest.com)')
        parser.add_argument('private_key', help='Private key')
        parser.add_argument('--node_url', default='http://localhost:8545',
                            help='Ethereum node in the same net that the relay')
        parser.add_argument('--payment-token', help='Use payment token for creating/testing')
        parser.add_argument('--create2', help='Use CREATE2 for safe creation', action='store_true', default=False)

    def send_eth(self, w3, account, to, value, nonce=None):
        tx = {
            'to': to,
            'value': value,
            'gas': 23000,
            'gasPrice': w3.eth.gasPrice,
            'nonce': nonce if nonce is not None else w3.eth.getTransactionCount(account.address,
                                                                                'pending'),
        }

        signed_tx = w3.eth.account.signTransaction(tx, private_key=account.privateKey)
        return w3.eth.sendRawTransaction(signed_tx.rawTransaction)

    def send_token(self, w3, account, to, amount_to_send, token_address, nonce=None):
        erc20_contract = get_erc20_contract(w3, token_address)
        nonce = nonce if nonce is not None else w3.eth.getTransactionCount(account.address, 'pending')
        tx = erc20_contract.functions.transfer(to, amount_to_send).buildTransaction({'from': account.address,
                                                                                     'nonce': nonce})
        signed_tx = w3.eth.account.signTransaction(tx, private_key=account.privateKey)
        return w3.eth.sendRawTransaction(signed_tx.rawTransaction)

    def get_safe_url(self, address):
        return urljoin(self.base_url, reverse('v1:safe', kwargs={'address': address}))

    def get_estimate_url(self, address):
        return urljoin(self.base_url, reverse('v1:safe-multisig-tx-estimate', kwargs={'address': address}))

    def get_tx_url(self, address):
        return urljoin(self.base_url, reverse('v1:safe-multisig-txs', kwargs={'address': address}))

    def get_signal_url(self, address):
        return urljoin(self.base_url, reverse('v1:safe-signal', kwargs={'address': address}))

    def handle(self, *args, **options):
        self.base_url = options['base_url']
        create2 = options['create2']
        every_test = options['all']
        payment_token = options['payment_token']

        self.w3 = Web3(HTTPProvider(options['node_url']))
        self.main_account = Account.privateKeyToAccount(options['private_key'])
        main_account_balance = self.w3.eth.getBalance(self.main_account.address)
        self.stdout.write(self.style.SUCCESS('Using %s as main account with balance=%d' % (self.main_account.address,
                                                                                           main_account_balance)))
        about_url = urljoin(self.base_url, reverse('v1:about'))
        about_json = requests.get(about_url).json()

        if create2:
            master_copy_address = about_json['settings']['SAFE_CONTRACT_ADDRESS']
        else:
            master_copy_address = about_json['settings']['SAFE_OLD_CONTRACT_ADDRESS']

        accounts = [Account.create() for _ in range(3)]
        for account in accounts:
            self.stdout.write(self.style.SUCCESS('Created account=%s with key=%s' % (account.address,
                                                                                     account.privateKey.hex())))
        accounts.append(self.main_account)
        accounts.sort(key=lambda account: account.address.lower())
        owners = [account.address for account in accounts]

        safe_address, payment = self.create_safe(owners, threshold=2, payment_token=payment_token, create2=create2)
        self.fund_safe(safe_address, payment, payment_token)
        safe_version = self.check_safe_deployed(safe_address, owners, master_copy_address)
        self.send_safe_tx(safe_address, safe_version, accounts, payment_token)

    def create_safe(self, owners: List[Account], threshold: int = 2,
                    payment_token: Optional[None] = None, create2: bool = True):
        if create2:
            creation_url = urljoin(self.base_url, reverse('v2:safe-creation'))
            data = {
                'saltNonce': generate_valid_s(),
                'owners': owners,
                'threshold': threshold,
            }
            if payment_token:
                data['paymentToken'] = payment_token
        else:
            creation_url = urljoin(self.base_url, reverse('v1:safe-creation'))
            data = {
                's': generate_valid_s(),
                'owners': owners,
                'threshold': threshold,
            }
            if payment_token:
                data['paymentToken'] = payment_token
        r = requests.post(creation_url, json=data)
        assert r.ok, "Error creating safe %s" % r.content

        safe_address, payment = r.json()['safe'], int(r.json()['payment'])
        return safe_address, payment

    def fund_safe(self, safe_address, payment, payment_token: Optional[None] = None):
        self.stdout.write(self.style.SUCCESS('Created safe=%s, need payment=%d' % (safe_address, payment)))
        if payment_token:
            tx_hash = self.send_token(self.w3, self.main_account, safe_address, payment, payment_token)
            self.stdout.write(self.style.SUCCESS('Sent payment of payment-token=%s, waiting for '
                                                 'receipt with tx-hash=%s' % (payment_token, tx_hash.hex())))
            self.w3.eth.waitForTransactionReceipt(tx_hash, timeout=500)

        tx_hash = self.send_eth(self.w3, self.main_account, safe_address, payment * 2)
        self.stdout.write(self.style.SUCCESS('Sent payment * 2, waiting for receipt with tx-hash=%s' % tx_hash.hex()))
        self.w3.eth.waitForTransactionReceipt(tx_hash, timeout=500)
        self.stdout.write(self.style.SUCCESS('Payment sent and mined. Waiting for safe to be deployed'))
        signal_url = self.get_signal_url(safe_address)
        r = requests.put(signal_url)
        assert r.ok, "Error sending signal that safe is funded %s" % r.content
        return safe_address

    def check_safe_deployed(self, safe_address, owners, master_copy_address):
        while True:
            if self.w3.eth.getCode(safe_address):
                break
            time.sleep(10)
        # Check safe was created successfully
        self.stdout.write(self.style.SUCCESS('Safe was deployed'))
        r = requests.get(self.get_safe_url(safe_address))
        assert r.ok, "Safe deployed is not working"
        safe_info = r.json()
        assert set(safe_info['owners']) == set(owners)
        assert safe_info['threshold'] == 2
        assert safe_info['nonce'] == 0
        assert safe_info['masterCopy'] == master_copy_address

        return safe_info['version']

    def send_safe_tx(self, safe_address, safe_version, accounts, payment_token):
        safe_balance = self.w3.eth.getBalance(safe_address)
        tx = {
            'to': self.main_account.address,
            'value': safe_balance,
            'data': None,
            'operation': 0,  # CALL
            'gasToken': payment_token,
        }

        if payment_token:
            tx['gasToken'] = payment_token

        # We used payment * 2 to fund the safe, now we return ether to the main account
        r = requests.post(self.get_estimate_url(safe_address), json=tx)
        assert r.ok, "Estimate not working %s" % r.content
        self.stdout.write(self.style.SUCCESS('Estimation=%s for tx=%s' % (r.json(), tx)))
        # estimate_gas = r.json()['safeTxGas'] + r.json()['dataGas'] + r.json()['operationalGas']
        # fees = r.json()['gasPrice'] * estimate_gas

        if payment_token:
            # We can transfer the full amount as we are paying fees with a token
            tx['value'] = safe_balance
        else:
            estimate_gas = r.json()['safeTxGas'] + r.json()['dataGas'] + r.json()['operationalGas'] + 1000
            fees = r.json()['gasPrice'] * estimate_gas
            tx['value'] = safe_balance - fees

        tx['dataGas'] = r.json()['dataGas']
        tx['gasPrice'] = r.json()['gasPrice']
        tx['safeTxGas'] = r.json()['safeTxGas']
        tx['nonce'] = r.json()['lastUsedNonce'] or 0
        tx['refundReceiver'] = None

        # Sign the tx
        safe_tx_hash = SafeService.get_hash_for_safe_tx(safe_address, tx['to'], tx['value'], tx['data'],
                                                        tx['operation'], tx['safeTxGas'], tx['dataGas'],
                                                        tx['gasPrice'], tx['gasToken'], tx['refundReceiver'],
                                                        tx['nonce'], safe_version=safe_version)

        signatures = [account.signHash(safe_tx_hash) for account in accounts[:2]]
        curated_signatures = [{'r': signature['r'], 's': signature['s'], 'v': signature['v']}
                              for signature in signatures]
        tx['signatures'] = curated_signatures

        self.stdout.write(self.style.SUCCESS('Sending multisig tx to return some funds to the main owner %s' % tx))
        r = requests.post(self.get_tx_url(safe_address), json=tx)
        assert r.ok, "Error sending tx %s" % r.content

        multisig_tx_hash = r.json()['txHash']
        self.stdout.write(self.style.SUCCESS('Tx with tx-hash=%s was successful' % multisig_tx_hash))
        self.w3.eth.waitForTransactionReceipt(multisig_tx_hash, timeout=500)
        return multisig_tx_hash
