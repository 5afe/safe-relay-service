from django.core.management.base import BaseCommand

from django_celery_beat.models import IntervalSchedule, PeriodicTask


class Command(BaseCommand):
    help = "Setup Gas Price calculation task"

    def handle(self, *args, **options):
        task_name = "safe_relay_service.gas_station.tasks.calculate_gas_prices"
        if PeriodicTask.objects.filter(task=task_name).count():
            self.stdout.write(self.style.SUCCESS("Task was already created"))
        else:
            interval, _ = IntervalSchedule.objects.get_or_create(
                every=5, period="minutes"
            )
            PeriodicTask.objects.create(
                name="Gas Price Calculation", task=task_name, interval=interval
            )
            self.stdout.write(
                self.style.SUCCESS(
                    "Created Periodic Task for Gas Price calculation every 5 minutes"
                )
            )
