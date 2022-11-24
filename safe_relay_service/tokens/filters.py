from django_filters import rest_framework as filters

from .models import Token


class TokenFilter(filters.FilterSet):
    default = filters.BooleanFilter(field_name="gas")

    class Meta:
        model = Token
        fields = {
            "name": ["exact"],
            "address": ["exact"],
            "symbol": ["exact"],
            "gas": ["exact"],
            "decimals": ["lt", "gt", "exact"],
        }
