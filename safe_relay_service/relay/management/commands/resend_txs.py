from django.core.management.base import BaseCommand

from safe_relay_service.gas_station.gas_station import GasStationProvider

from ...models import SafeMultisigTx
from ...services import TransactionServiceProvider


class Command(BaseCommand):
    help = (
        "Resend txs using a higher gas price. Use this command to allow stuck txs go through. If no options"
        "are specified all txs with gas price less than current fast price on GasStation will be sent"
    )

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument(
            "--gas-price",
            help="Resend all txs below this gas-price using this gas price",
            type=int,
        )
        parser.add_argument("--safe-tx-hash", help="Resend tx with safe tx hash")
        parser.add_argument(
            "--older", help="Resend tx older than x seconds", type=int, default=60
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tx_service = TransactionServiceProvider()

    def handle(self, *args, **options):
        gas_price = options["gas_price"] or GasStationProvider().get_gas_prices().fast
        safe_tx_hash = options["safe_tx_hash"]
        older = options["older"]

        if safe_tx_hash:
            multisig_tx = SafeMultisigTx.objects.get(safe_tx_hash=safe_tx_hash)
            self.tx_service.resend(gas_price, multisig_tx)
        else:
            for multisig_tx in SafeMultisigTx.objects.pending(
                older_than=older
            ).select_related("ethereum_tx"):
                self.tx_service.resend(gas_price, multisig_tx)
