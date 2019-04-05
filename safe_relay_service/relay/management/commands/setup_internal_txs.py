from django.core.management.base import BaseCommand

from ...models import SafeContract, SafeTxStatus
from ...services import InternalTxServiceProvider


class Command(BaseCommand):
    help = 'Prepare models for internal txs'

    def handle(self, *args, **options):
        count_safe_tx_status = SafeTxStatus.objects.count()
        for safe_contract in SafeContract.objects.deployed():
            InternalTxServiceProvider().get_or_create_safe_tx_status(safe_contract.address)

        created_safe_tx_status = SafeTxStatus.objects.count() - count_safe_tx_status
        self.stdout.write(self.style.SUCCESS('Generated %d SafeTxStatus' % created_safe_tx_status))
