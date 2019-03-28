from django.core.management.base import BaseCommand

from gnosis.eth import EthereumClientProvider

from ...models import Token


class Command(BaseCommand):
    help = 'Update list of tokens'

    def add_arguments(self, parser):
        # Positional arguments
        parser.add_argument('tokens', nargs='+', help='Token/s address/es to add to the token list')
        parser.add_argument('--no-prompt', help='If set, add the tokens without prompt', action='store_true',
                            default=False)

    def handle(self, *args, **options):
        tokens = options['tokens']
        no_prompt = options['no_prompt']
        ethereum_client = EthereumClientProvider()

        for token_address in tokens:
            token_address = ethereum_client.w3.toChecksumAddress(token_address)
            info = ethereum_client.erc20.get_info(token_address)
            if no_prompt:
                response = 'y'
            else:
                response = input('Do you want to create a token {} (y/n) '.format(info)).strip().lower()
            if response == 'y':
                Token.objects.create(address=token_address, name=info.name, symbol=info.symbol, decimals=info.decimals)
                self.stdout.write(self.style.SUCCESS('Created token %s' % info.name))
