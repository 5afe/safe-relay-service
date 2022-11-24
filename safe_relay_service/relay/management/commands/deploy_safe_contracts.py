from django.conf import settings
from django.core.management.base import BaseCommand

from eth_account import Account

from gnosis.eth import EthereumClientProvider
from gnosis.safe import ProxyFactory, Safe


class Command(BaseCommand):
    help = (
        "Deploys master copy using first unlocked account on the node if `ganache -d` is found and contract "
        "is not deployed. If not you need to set a private key using `--deployer-key`"
    )
    GANACHE_FIRST_ACCOUNT_KEY = (
        "0x4f3edf983ac636a65a842ce7c78d9aa706d3b113bce9c46f30d7d21715b23b1d"
    )
    DEFAULT_ACCOUNT = Account.from_key(GANACHE_FIRST_ACCOUNT_KEY)

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument("--deployer-key", help="Private key for deployer")

    def handle(self, *args, **options):
        ethereum_client = EthereumClientProvider()
        deployer_key = options["deployer_key"]
        deployer_account = (
            Account.from_key(deployer_key) if deployer_key else self.DEFAULT_ACCOUNT
        )

        master_copies_with_deploy_fn = {
            settings.SAFE_CONTRACT_ADDRESS: Safe.deploy_master_contract_v1_3_0,
            settings.SAFE_PROXY_FACTORY_ADDRESS: ProxyFactory.deploy_proxy_factory_contract,
            settings.SAFE_V1_0_0_CONTRACT_ADDRESS: Safe.deploy_master_contract_v1_0_0,
        }

        for master_copy_address, deploy_fn in master_copies_with_deploy_fn.items():
            self.stdout.write(
                self.style.SUCCESS(
                    f"Checking if contract was already deployed on "
                    f"{master_copy_address}"
                )
            )
            if ethereum_client.is_contract(master_copy_address):
                self.stdout.write(
                    self.style.NOTICE(
                        f"Master copy was already deployed on {master_copy_address}"
                    )
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Deploying contract using deployer account, "
                        f"address={master_copy_address} not found"
                    )
                )
                master_copy_address = deploy_fn(
                    ethereum_client, deployer_account=deployer_account
                ).contract_address
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Contract has been deployed on {master_copy_address}"
                    )
                )
