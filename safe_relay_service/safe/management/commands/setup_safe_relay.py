from django.core.management.base import BaseCommand
from django_celery_beat.models import IntervalSchedule, PeriodicTask


class Command(BaseCommand):
    help = 'Setup Safe relay required tasks'

    def handle(self, *args, **options):
        task_name = 'safe_relay_service.safe.tasks.deploy_safes_task'
        if PeriodicTask.objects.filter(task=task_name).count():
            self.stdout.write(self.style.SUCCESS('Task was already created'))
        else:
            interval, _ = IntervalSchedule.objects.get_or_create(every=20, period='seconds')
            PeriodicTask.objects.create(
                name='Deploy Safes Task',
                task=task_name,
                interval=interval
            )
            self.stdout.write(self.style.SUCCESS('Created Periodic Task for Safe deployment every minute'))
