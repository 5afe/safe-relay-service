from django.core.management.base import BaseCommand
from django_celery_beat.models import IntervalSchedule, PeriodicTask


class Command(BaseCommand):
    help = 'Setup Gas Price calculation task'

    def handle(self, *args, **options):
        if PeriodicTask.objects.filter(task='safe_relay_service.gas_station.tasks.calculate_gas_prices').count():
            self.stdout.write(self.style.SUCCESS('Task was already created'))
        else:
            interval = IntervalSchedule(every=5, period='minutes')
            interval.save()
            PeriodicTask.objects.create(
                name='Gas Price Calculation',
                task='safe_relay_service.gas_station.tasks.calculate_gas_prices',
                interval=interval
            )
            self.stdout.write(self.style.SUCCESS('Created Periodic Task for Gas Price calculation every 5 minutes'))
