from django.conf import settings
from hexbytes import HexBytes
from web3 import Web3
from web3.middleware import geth_poa_middleware

from safe_relay_service.ether.utils import NULL_ADDRESS

from .abis import load_contract_interface

"""
Rinkeby contracts https://github.com/gnosis/safe-contracts/releases/tag/v0.0.1
-----------------
ProxyFactory: 0x075794c3797bb4cfea74a75d1aae636036af37cd
GnosisSafePersonalEdition: 0x44E7f5855A77FE1793A96BE8a1c9C3Eaf47E9D09
GnosisSafeTeamEdition: 0x607c2ea232621ad2221201511f7982d870f1afe5
DailyLimitModule: 0xac94a500b707fd5c4cdb89777f29b3b28bde2f0c
CreateAndAddModules: 0x8513246e65c474ad05e88ae8ca7c5a6b04246550
MultiSend: 0x7830ceb6f513568c05bd995d0767cceea2ef9662
"""

GNOSIS_SAFE_PERSONAL_INTERFACE = load_contract_interface('GnosisSafePersonalEdition.json')
PAYING_PROXY_INTERFACE = load_contract_interface('PayingProxy.json')


def get_safe_personal_contract(w3: Web3, address=None):
    """
    Get Safe Contract. It should be used to access Safe methods on Proxy contracts.
    :param w3: Web3 instance
    :param address: address of the safe contract/proxy contract
    :return: Safe Contract
    """
    address = settings.SAFE_PERSONAL_CONTRACT_ADDRESS if not address else address
    return w3.eth.contract(address,
                           abi=GNOSIS_SAFE_PERSONAL_INTERFACE['abi'],
                           bytecode=GNOSIS_SAFE_PERSONAL_INTERFACE['bytecode'])


def get_paying_proxy_contract(w3: Web3, address=NULL_ADDRESS):
    """
    Get Paying Proxy Contract. This should be used just for contract creation/changing master_copy
    If you want to call Safe methods you should use `get_safe_contract` with the Proxy address,
    so you can access every method of the Safe
    :param w3: Web3 instance
    :param address: address of the proxy contract
    :return: Paying Proxy Contract
    """
    return w3.eth.contract(address,
                           abi=PAYING_PROXY_INTERFACE['abi'],
                           bytecode=PAYING_PROXY_INTERFACE['bytecode'])


def get_paying_proxy_deployed_bytecode() -> bytes:
    return HexBytes(PAYING_PROXY_INTERFACE['deployedBytecode'])
