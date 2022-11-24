from django.core.management.base import BaseCommand

from gnosis.eth import EthereumClientProvider

from ...models import SafeContract


class Command(BaseCommand):
    help = "Check internal tx balances matches the ones from the ethereum blockchain"

    def handle(self, *args, **options):
        ethereum_client = EthereumClientProvider()
        mismatchs = 0
        for safe_contract in SafeContract.objects.deployed():
            blockchain_balance = ethereum_client.get_balance(safe_contract.address)
            internal_tx_balance = safe_contract.get_balance()
            if blockchain_balance != internal_tx_balance:
                mismatchs += 1
                self.stdout.write(
                    self.style.NOTICE(
                        f"safe={safe_contract.address} "
                        f"blockchain-balance={blockchain_balance} does not match "
                        f"internal-tx-balance={internal_tx_balance}"
                    )
                )
        if mismatchs:
            self.stdout.write(
                self.style.NOTICE(f"{mismatchs} Safes don't match blockchain balance")
            )
        else:
            self.stdout.write(self.style.SUCCESS("All Safes match blockchain balance"))
