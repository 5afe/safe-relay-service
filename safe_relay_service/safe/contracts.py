from django.conf import settings

from .abis import load_contract_interface
from .utils import NULL_ADDRESS

"""
Rinkeby contracts
-----------------
ProxyFactory: 0x075794c3797bb4cfea74a75d1aae636036af37cd
GnosisSafePersonalEdition: 0xec7c75c1548765ab51a165873b0b1b71663c1266
GnosisSafeTeamEdition: 0x607c2ea232621ad2221201511f7982d870f1afe5
DailyLimitModule: 0xac94a500b707fd5c4cdb89777f29b3b28bde2f0c
CreateAndAddModules: 0x8513246e65c474ad05e88ae8ca7c5a6b04246550
MultiSend: 0x7830ceb6f513568c05bd995d0767cceea2ef9662
"""

GNOSIS_SAFE_INTERFACE = load_contract_interface('GnosisSafe.json')
PAYING_PROXY_INTERFACE = load_contract_interface('PayingProxy.json')


def get_safe_contract(w3, address=settings.SAFE_PERSONAL_CONTRACT_ADDRESS):
    return w3.eth.contract(address,
                           abi=GNOSIS_SAFE_INTERFACE['abi'],
                           bytecode=GNOSIS_SAFE_INTERFACE['bytecode'])


def get_paying_proxy_contract(w3, address=NULL_ADDRESS):
    return w3.eth.contract(address,
                           abi=PAYING_PROXY_INTERFACE['abi'],
                           bytecode=PAYING_PROXY_INTERFACE['bytecode'])
