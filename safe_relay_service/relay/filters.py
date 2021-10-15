import django_filters
from django_filters import rest_framework as filters
from rest_framework.pagination import LimitOffsetPagination

from gnosis.eth.django.models import Uint256Field

from .models import SafeMultisigTx


class DefaultPagination(LimitOffsetPagination):
    max_limit = 200
    default_limit = 100


class SafeMultisigTxFilter(filters.FilterSet):
    class Meta:
        model = SafeMultisigTx
        fields = {
            "to": ["exact"],
            "value": ["lt", "gt", "exact"],
            "operation": ["exact"],
            "safe_tx_gas": ["lt", "gt", "exact"],
            "data_gas": ["lt", "gt", "exact"],
            "gas_price": ["lt", "gt", "exact"],
            "nonce": ["lt", "gt", "exact"],
            "gas_token": ["exact"],
            "safe_tx_hash": ["exact"],
            "ethereum_tx__tx_hash": ["exact"],
        }
        filter_overrides = {Uint256Field: {"filter_class": django_filters.NumberFilter}}
