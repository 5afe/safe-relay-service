from django.core.management.base import BaseCommand

from ....version import __version__


class Command(BaseCommand):
    help = 'get version'

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS(__version__))
