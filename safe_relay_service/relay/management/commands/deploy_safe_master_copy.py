from django.core.management.base import BaseCommand
from gnosis.safe.safe_service import SafeServiceProvider


class Command(BaseCommand):
    help = 'Deploys master copy using first unlocked account on the node if `ganache -d` is found and contract ' \
           'is not deployed. If not you need to set a private key or an unlocked account on the node'
    GANACHE_FIRST_ACCOUNT = '0x90F8bf6A479f320ead074411a4B0e7944Ea8c9C1'

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('--deployer-key', help='Private key for deployer')
        parser.add_argument('--deployer-account', help='Public key unlocked in node for deployer')

    def handle(self, *args, **options):
        safe_service = SafeServiceProvider()
        account = safe_service.w3.eth.accounts[0] if safe_service.w3.eth.accounts else None
        deployer_key = options['deployer_key']
        deployer_account = options['deployer_account']
        master_copy_address = None
        proxy_factory_address = None
        subscription_module_address = None
        create_add_modules_address = None
        ds_feed_contract_address = None
        oracle_registry_contract_address = None

        self.stdout.write("TEST!!!!!!!!!!!")
        self.stdout.write(account)
        self.stdout.write(self.GANACHE_FIRST_ACCOUNT)
        self.stdout.write("TEST!!!!!!!!!!!")
        if deployer_key:
            self.stdout.write(self.style.SUCCESS('Deploying master copy using deployer key'))
            master_copy_address = safe_service.deploy_master_contract(
                deployer_key=deployer_key
            )
            # proxy_contract_address = safe_service.deploy_proxy_contract(deployer_key=deployer_key)
            proxy_factory_address = safe_service.deploy_proxy_factory_contract(
                deployer_key=deployer_key
            )
            subscription_module_address = safe_service.deploy_subscription_module_contract(
                deployer_key=deployer_key
            )
            merchant_module_address = safe_service.deploy_merchant_module_contract(
                deployer_key=deployer_key
            )
            create_add_modules_address = safe_service.deploy_create_add_modules_contract(
                deployer_key=deployer_key
            )
            ds_feed_contract_address = safe_service.deploy_ds_feed_contract(
                deployer_key=deployer_key
            )
            bulk_executor_address = safe_service.deploy_bulk_executor(
                deployer_key=deployer_key
            )
            oracle_registry_contract_address = safe_service.deploy_oracle_registry_contract(
                deployer_key=deployer_key,
                ds_feed_contract_address=ds_feed_contract_address,
                network_wallet=deployer_account,
                bulk_executor_address=bulk_executor_address
            )

        elif deployer_account:
            self.stdout.write(self.style.SUCCESS('Deploying master copy using deployer account'))
            master_copy_address = safe_service.deploy_master_contract(
                deployer_account=deployer_account
            )
            # proxy_contract_address = safe_service.deploy_proxy_contract(deployer_account=deployer_account)
            proxy_factory_address = safe_service.deploy_proxy_factory_contract(
                deployer_account=deployer_account
            )
            subscription_module_address = safe_service.deploy_subscription_module_contract(
                deployer_account=deployer_account
            )
            merchant_module_address = safe_service.deploy_merchant_module_contract(
                deployer_account=deployer_account
            )
            create_add_modules_address = safe_service.deploy_create_add_modules_contract(
                deployer_account=deployer_account
            )
            ds_feed_contract_address = safe_service.deploy_ds_feed_contract(
                deployer_account=deployer_account
            )
            bulk_executor_address = safe_service.deploy_bulk_executor(
                deployer_account=deployer_account
            )

            oracle_registry_contract_address = safe_service.deploy_oracle_registry_contract(
                deployer_account=deployer_account,
                ds_feed_contract_address=ds_feed_contract_address,
                network_wallet=deployer_account,
                bulk_executor_address=bulk_executor_address
            )

        elif account == self.GANACHE_FIRST_ACCOUNT:
            self.stdout.write(self.style.SUCCESS('Ganache detected, deploying master copy if not deployed'))
            master_copy_address = safe_service.deploy_master_contract(
                deployer_account=account
            )
            # proxy_contract_address = safe_service.deploy_proxy_contract(deployer_account=account)
            proxy_factory_address = safe_service.deploy_proxy_factory_contract(
                deployer_account=account
            )
            subscription_module_address = safe_service.deploy_subscription_module_contract(
                deployer_account=account
            )
            merchant_module_address = safe_service.deploy_merchant_module_contract(
                deployer_account=account
            )
            create_add_modules_address = safe_service.deploy_create_add_modules_contract(
                deployer_account=account
            )
            ds_feed_contract_address = safe_service.deploy_ds_feed_contract(
                deployer_account=account
            )
            bulk_executor_address = safe_service.deploy_bulk_executor(
                deployer_account=account
            )

            oracle_registry_contract_address = safe_service.deploy_oracle_registry_contract(
                deployer_account=account,
                ds_feed_contract_address=ds_feed_contract_address,
                network_wallet=deployer_account,
                bulk_executor_address=bulk_executor_address
            )

        else:
            self.stdout.write(self.style.NOTICE('Nothing done'))

        if master_copy_address:
            self.stdout.write(self.style.SUCCESS('Master copy deployed on %s' % master_copy_address))
            self.stdout.write(self.style.SUCCESS('Proxy Factory contract deployed on %s' % proxy_factory_address))
            self.stdout.write(
                self.style.SUCCESS('SubscriptionModule contract deployed on %s' % subscription_module_address))
            self.stdout.write(self.style.SUCCESS('MerchantModule contract deployed on %s' % merchant_module_address))
            self.stdout.write(self.style.SUCCESS('Bulk Executor contract deployed on %s' % bulk_executor_address))
            self.stdout.write(
                self.style.SUCCESS('Get Create Add Modules contract deployed on %s' % create_add_modules_address))
            self.stdout.write(self.style.SUCCESS('DS Feed contract deployed on %s' % ds_feed_contract_address))
            self.stdout.write(
                self.style.SUCCESS('Oracle Registry contract deployed on %s' % oracle_registry_contract_address))
        else:
            self.stdout.write(self.style.NOTICE('Master copy not deployed'))
