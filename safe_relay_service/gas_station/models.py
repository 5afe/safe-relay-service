from django.db import models

from model_utils.models import TimeStampedModel


class GasPrice(TimeStampedModel):
    lowest = models.BigIntegerField()
    safe_low = models.BigIntegerField()
    standard = models.BigIntegerField()
    fast = models.BigIntegerField()
    fastest = models.BigIntegerField()

    class Meta:
        get_latest_by = "created"

    def __str__(self):
        return "%s lowest=%d safe_low=%d standard=%d fast=%d fastest=%d" % (
            self.created,
            self.lowest,
            self.safe_low,
            self.standard,
            self.fast,
            self.fastest,
        )
