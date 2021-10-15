from django.core.management.base import BaseCommand

from ...models import SafeFunding


class Command(BaseCommand):
    help = "Check status of not deployed safes"

    def handle(self, *args, **options):
        safe_fundings = SafeFunding.objects.not_deployed()
        if not safe_fundings:
            self.stdout.write(self.style.SUCCESS("All safes are deployed"))
        for safe_funding in safe_fundings:
            self.stdout.write(
                self.style.SUCCESS(
                    "Safe={} Status={}".format(
                        safe_funding.safe.address, safe_funding.status()
                    )
                )
            )
