import factory.fuzzy
from factory.django import DjangoModelFactory

from ..models import GasPrice


class GasPriceFactory(DjangoModelFactory):
    class Meta:
        model = GasPrice

    lowest = factory.fuzzy.FuzzyInteger(0, 1000)
    safe_low = factory.fuzzy.FuzzyInteger(2000, 3000)
    standard = factory.fuzzy.FuzzyInteger(4000, 6000)
    fast = factory.fuzzy.FuzzyInteger(7000, 14000)
    fastest = factory.fuzzy.FuzzyInteger(15000, 20000)
