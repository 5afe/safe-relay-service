from typing import NamedTuple, Tuple

from django.core.management.base import BaseCommand

from django_celery_beat.models import IntervalSchedule, PeriodicTask


class CeleryTaskConfiguration(NamedTuple):
    name: str
    description: str
    interval: int
    period: str

    def create_task(self) -> Tuple[PeriodicTask, bool]:
        interval, _ = IntervalSchedule.objects.get_or_create(every=self.interval, period=self.period)
        return PeriodicTask.objects.get_or_create(task=self.name,
                                                  defaults={
                                                      'name': self.description,
                                                      'interval': interval
                                                  })


class Command(BaseCommand):
    help = 'Setup Safe relay required tasks'
    tasks = [CeleryTaskConfiguration('safe_relay_service.relay.tasks.deploy_safes_task',
                                     'Deploy Safes', 20, IntervalSchedule.SECONDS),
             CeleryTaskConfiguration('safe_relay_service.relay.tasks.check_balance_of_accounts_task',
                                     'Check Balance of realy accounts', 1, IntervalSchedule.HOURS),
             CeleryTaskConfiguration('safe_relay_service.relay.tasks.check_create2_deployed_safes_task',
                                     'Check and deploy Create2 Safes', 1, IntervalSchedule.MINUTES),
             CeleryTaskConfiguration('safe_relay_service.relay.tasks.find_internal_txs_task',
                                     'Process Internal Txs for Safes', 2, IntervalSchedule.MINUTES),
             CeleryTaskConfiguration('safe_relay_service.relay.tasks.find_erc_20_721_transfers_task',
                                     'Process ERC20/721 transfers for Safes', 2, IntervalSchedule.MINUTES),
             ]

    def handle(self, *args, **options):
        for task in self.tasks:
            _, created = task.create_task()
            if created:
                self.stdout.write(self.style.SUCCESS('Created Periodic Task %s' % task.name))
            else:
                self.stdout.write(self.style.SUCCESS('Task %s was already created' % task.name))

