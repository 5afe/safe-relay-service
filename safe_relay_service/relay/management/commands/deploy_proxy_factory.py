from django.conf import settings
from django.core.management.base import BaseCommand

from eth_account import Account

from gnosis.eth import EthereumClientProvider
from gnosis.safe import ProxyFactory


class Command(BaseCommand):
    help = (
        "Deploys proxy factory using first unlocked account on the node if `ganache -d` is found and contract "
        "is not deployed. If not you need to set a private key using `--deployer-key`"
    )
    GANACHE_FIRST_ACCOUNT_KEY = (
        "0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d"
    )
    DEFAULT_ACCOUNT = Account.privateKeyToAccount(GANACHE_FIRST_ACCOUNT_KEY)

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument("--deployer-key", help="Private key for deployer")

    def handle(self, *args, **options):
        ethereum_client = EthereumClientProvider()
        proxy_factory_address = settings.SAFE_PROXY_FACTORY_ADDRESS
        deployer_key = options["deployer_key"]
        deployer_account = (
            Account.privateKeyToAccount(deployer_key)
            if deployer_key
            else self.DEFAULT_ACCOUNT
        )

        self.stdout.write(
            self.style.SUCCESS(
                "Checking if proxy factory was already deployed on %s"
                % proxy_factory_address
            )
        )
        if ethereum_client.is_contract(proxy_factory_address):
            self.stdout.write(
                self.style.NOTICE(
                    "Proxy factory was already deployed on %s" % proxy_factory_address
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    "Deploying proxy factory using deployer account, "
                    "proxy factory %s not found" % proxy_factory_address
                )
            )
            proxy_factory_address = ProxyFactory.deploy_proxy_factory_contract(
                ethereum_client, deployer_account=deployer_account
            ).contract_address
            self.stdout.write(
                self.style.SUCCESS(
                    "Proxy factory has been deployed on %s" % proxy_factory_address
                )
            )
