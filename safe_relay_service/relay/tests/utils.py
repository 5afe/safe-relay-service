import os

from ethereum.transactions import secpk1n

from gnosis.eth.utils import get_eth_address_with_key
from gnosis.safe.tests.factories import generate_valid_s
from ..relay_service import RelayServiceProvider

from ..models import SafeCreation


#FIXME Use the functions in gnosis-py
def generate_valid_s():
    while True:
        s = int(os.urandom(30).hex(), 16)
        if s <= (secpk1n // 2):
            return s


def generate_safe(owners=None, number_owners=3, threshold=None, payment_token=None) -> SafeCreation:
    s = generate_valid_s()

    if not owners:
        owners = []
        for _ in range(number_owners):
            owner, _ = get_eth_address_with_key()
            owners.append(owner)

    threshold = threshold if threshold else len(owners)

    safe_creation = RelayServiceProvider().create_safe_tx(s, owners, threshold, payment_token)
    return safe_creation


def deploy_safe(w3, safe_creation, funder: str, initial_funding_wei: int=0) -> str:
    w3.eth.waitForTransactionReceipt(
        w3.eth.sendTransaction({
            'from': funder,
            'to': safe_creation.deployer,
            'value': safe_creation.payment
        })
    )

    w3.eth.waitForTransactionReceipt(
        w3.eth.sendTransaction({
            'from': funder,
            'to': safe_creation.safe.address,
            'value': safe_creation.payment
        })
    )

    tx_hash = w3.eth.sendRawTransaction(bytes(safe_creation.signed_tx))
    tx_receipt = w3.eth.waitForTransactionReceipt(tx_hash)
    assert tx_receipt.contractAddress == safe_creation.safe.address
    assert tx_receipt.status

    if initial_funding_wei > 0:
        w3.eth.waitForTransactionReceipt(
            w3.eth.sendTransaction({
                'from': funder,
                'to': safe_creation.safe.address,
                'value': initial_funding_wei
            })
        )

    return safe_creation.safe.address
