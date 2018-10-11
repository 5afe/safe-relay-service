import argparse
import logging
import os
from urllib.parse import urljoin

import requests
from ethereum.utils import checksum_encode, privtoaddr
from web3 import HTTPProvider, Web3

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(levelname)s - %(message)s')

w3 = Web3(HTTPProvider('https://rinkeby.infura.io/gnosis'))

parser = argparse.ArgumentParser()
parser.add_argument("number", help="number of safes to create", type=int)
parser.add_argument("url", help="base url of service")
parser.add_argument("owners", help="owners split by commas")
parser.add_argument("private_key", help="private key to fund the safes")
args = parser.parse_args()

SAFE_BASE_URL = args.url
SAFES_URL = urljoin(SAFE_BASE_URL, '/api/v1/safes/')


def get_safes_notify_url(address):
    return urljoin(SAFES_URL, address + '/funded/')


def send_eth(private_key, to, value, nonce):
    tx = {
        'to': to,
        'value': value,
        'gas': 23000,
        'gasPrice': w3.eth.gasPrice,
        'nonce': nonce,
    }

    signed_tx = w3.eth.account.signTransaction(tx, private_key=private_key)
    return w3.eth.sendRawTransaction(signed_tx.rawTransaction)


def generate_valid_s():
    return int(os.urandom(31).hex(), 16)


def generate_payload(owners, threshold=None):
    return {"owners": owners,
            "s": generate_valid_s(),
            "threshold": threshold if threshold else len(owners)
            }


def notify_safes():
    with open('safes.txt', mode='r') as safes_file:
        for safe_address in safes_file:
            r = requests.put(get_safes_notify_url(safe_address.strip()))
            assert r.ok


def deploy_safes(number, owners, private_key):
    safes = []
    funding_public_key = checksum_encode(privtoaddr(private_key))
    funding_nonce = w3.eth.getTransactionCount(funding_public_key, 'pending')
    for _ in range(number):
        payload_json = generate_payload(owners)
        r = requests.post(SAFES_URL, json=payload_json)
        assert r.ok
        safe_created = r.json()
        safe_address = safe_created['safe']
        payment = int(safe_created['payment'])

        logging.info('Created safe=%s, need payment=%d', safe_address, payment)
        send_eth(private_key, safe_address, payment, funding_nonce)
        logging.info('Sent payment=%s to safe=%s', payment, safe_address)
        r = requests.put(get_safes_notify_url(safe_address))
        assert r.ok
        funding_nonce += 1
        safes.append(safe_address)

    with open('safes.txt', mode='a') as safes_file:
        safes_file.write('\n'.join(safes))


# notify_safes()
owners = [x.strip() for x in args.owners.split(',')]
deploy_safes(args.number, owners, args.private_key)
