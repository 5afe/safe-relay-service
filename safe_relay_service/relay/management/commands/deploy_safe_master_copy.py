from django.core.management.base import BaseCommand

from gnosis.safe.safe_service import SafeServiceProvider


# TODO Allow it to accept private keys
class Command(BaseCommand):
    help = 'Deploys master copy using first unlocked account on the node. For using it with `ganache -d`'

    def handle(self, *args, **options):
        safe_service = SafeServiceProvider()
        account = safe_service.w3.eth.accounts[0]

        master_copy_address = safe_service.deploy_master_contract(deployer_account=account)
        self.stdout.write(self.style.SUCCESS('Master copy deployed on %s' % master_copy_address))
