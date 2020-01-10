from django.core.management.base import BaseCommand
from django.db.models import F

from ...models import SafeMultisigTx


class Command(BaseCommand):
    help = 'Fix SafeTxHash typo'

    def handle(self, *args, **options):
        for safe_multisig_tx in SafeMultisigTx.objects.filter(ethereum_tx_id=F('safe_tx_hash')):
            safe_tx = safe_multisig_tx.get_safe_tx()
            self.stdout.write(self.style.SUCCESS(f'Fixing safe-multisig-tx with '
                                                 f'tx-hash={safe_multisig_tx.ethereum_tx_id}'))
            safe_multisig_tx.safe_tx_hash = safe_tx.safe_tx_hash
            safe_multisig_tx.save(update_fields=['safe_tx_hash'])
