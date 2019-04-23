from django.core.management.base import BaseCommand

from django_celery_beat.models import IntervalSchedule, PeriodicTask


class Command(BaseCommand):
    help = 'Setup Safe relay required tasks'

    def handle(self, *args, **options):
        task_name = 'safe_relay_service.relay.tasks.deploy_safes_task'
        if PeriodicTask.objects.filter(task=task_name).count():
            self.stdout.write(self.style.SUCCESS('Task %s was already created' % task_name))
        else:
            interval, _ = IntervalSchedule.objects.get_or_create(every=20, period='seconds')
            PeriodicTask.objects.create(
                name='Deploy Safes Task',
                task=task_name,
                interval=interval
            )
            self.stdout.write(self.style.SUCCESS('Created Periodic Task %s' % task_name))

        task_name = 'safe_relay_service.relay.tasks.check_balance_of_accounts_task'
        if PeriodicTask.objects.filter(task=task_name).count():
            self.stdout.write(self.style.SUCCESS('Task %s was already created' % task_name))
        else:
            interval, _ = IntervalSchedule.objects.get_or_create(every=1, period='hours')
            PeriodicTask.objects.create(
                name='Check balance of relay accounts Task',
                task=task_name,
                interval=interval
            )
            self.stdout.write(self.style.SUCCESS('Created Periodic Task %s' % task_name))

        task_name = 'safe_relay_service.relay.tasks.check_create2_deployed_safes_task'
        if PeriodicTask.objects.filter(task=task_name).count():
            self.stdout.write(self.style.SUCCESS('Task %s was already created' % task_name))
        else:
            interval, _ = IntervalSchedule.objects.get_or_create(every=1, period='minutes')
            PeriodicTask.objects.create(
                name='Check if create2 safes were deployed ',
                task=task_name,
                interval=interval
            )
            self.stdout.write(self.style.SUCCESS('Created Periodic Task %s' % task_name))

        task_name = 'safe_relay_service.relay.tasks.find_internal_txs_task'
        if PeriodicTask.objects.filter(task=task_name).count():
            self.stdout.write(self.style.SUCCESS('Task %s was already created' % task_name))
        else:
            interval, _ = IntervalSchedule.objects.get_or_create(every=2, period='minutes')
            PeriodicTask.objects.create(
                name='Process Internal txs',
                task=task_name,
                interval=interval
            )
            self.stdout.write(self.style.SUCCESS('Created Periodic Task %s' % task_name))
