from django.core.management.base import BaseCommand
from django.conf import settings
from eth_account import Account
from gnosis.eth import EthereumClientProvider

from gnosis.safe import Safe


class Command(BaseCommand):
    help = 'Deploys master copy using first unlocked account on the node if `ganache -d` is found and contract ' \
           'is not deployed. If not you need to set a private key using `--deployer-key`'
    GANACHE_FIRST_ACCOUNT_KEY = '0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d'
    DEFAULT_ACCOUNT = Account.privateKeyToAccount(GANACHE_FIRST_ACCOUNT_KEY)

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('--deployer-key', help='Private key for deployer')

    def handle(self, *args, **options):
        ethereum_client = EthereumClientProvider()
        master_copy_address = settings.SAFE_CONTRACT_ADDRESS
        deployer_key = options['deployer_key']
        deployer_account = Account.privateKeyToAccount(deployer_key) if deployer_key else self.DEFAULT_ACCOUNT

        self.stdout.write(self.style.SUCCESS('Checking if Master copy was already deployed on %s' %
                                             master_copy_address))
        if ethereum_client.is_contract(master_copy_address):
            self.stdout.write(self.style.NOTICE('Master copy was already deployed on %s' % master_copy_address))
        else:
            self.stdout.write(self.style.SUCCESS('Deploying master copy using deployer account, '
                                                 'master copy %s not found' % master_copy_address))
            master_copy_address = Safe.deploy_master_contract(ethereum_client,
                                                              deployer_account=deployer_account).contract_address
            self.stdout.write(self.style.SUCCESS('Master copy deployed on %s' % master_copy_address))
