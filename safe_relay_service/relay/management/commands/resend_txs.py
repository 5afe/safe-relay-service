from django.core.management.base import BaseCommand

from safe_relay_service.gas_station.gas_station import GasStationProvider

from ...models import EthereumTx, SafeMultisigTx
from ...services import TransactionServiceProvider


class Command(BaseCommand):
    help = 'Resend txs using a higher gas price. Use this command to allow stuck txs go through. If no options' \
           'are specified all txs with gas price less than current fast price on GasStation will be sent'

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('--gas-price', help='Resend all txs below this gas-price using this gas price')
        parser.add_argument('--safe-tx-hash', help='Resend tx with safe tx hash')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.tx_service = TransactionServiceProvider()

    def resend(self, gas_price: int, multisig_tx: SafeMultisigTx):
        #TODO Refactor, do it on the service
        if multisig_tx.ethereum_tx.gas_price < gas_price:
            assert multisig_tx.ethereum_tx.block_id is None, 'Block is present!'
            self.stdout.write(self.style.NOTICE(
                f"{multisig_tx.ethereum_tx_id} tx gas price is {multisig_tx.ethereum_tx.gas_price} < {gas_price}. "
                f"Resending with new gas price {gas_price}"
            ))
            safe_tx = multisig_tx.get_safe_tx(self.tx_service.ethereum_client)
            tx_gas = safe_tx.base_gas + safe_tx.safe_tx_gas + 25000
            tx_hash, tx = safe_tx.execute(self.tx_service.tx_sender_account.key, tx_gas=tx_gas,
                                          tx_gas_price=gas_price, tx_nonce=multisig_tx.ethereum_tx.nonce)
            multisig_tx.ethereum_tx = EthereumTx.objects.create_from_tx(tx, tx_hash)
            multisig_tx.save(update_fields=['ethereum_tx'])
        else:
            self.stdout.write(self.style.NOTICE(
                f"{multisig_tx.ethereum_tx_id} tx gas price is {multisig_tx.ethereum_tx.gas_price} > {gas_price}. "
                f"Nothing to do here"
            ))

    def handle(self, *args, **options):
        gas_price = options['gas_price'] or GasStationProvider().get_gas_prices().fast
        safe_tx_hash = options['safe_tx_hash']

        if safe_tx_hash:
            multisig_tx = SafeMultisigTx.objects.get(safe_tx_hash=safe_tx_hash)
            self.resend(gas_price, multisig_tx)
        else:
            for multisig_tx in SafeMultisigTx.objects.pending(older_than=60):
                self.resend(gas_price, multisig_tx)
