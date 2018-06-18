from django.conf.urls import url
from django.urls import path

from safe_relay_service.gas_station.views import GasStationView

from . import views

app_name = "safe"

timestamp_regex = '\\d{4}[-]?\\d{1,2}[-]?\\d{1,2} \\d{1,2}:\\d{1,2}:\\d{1,2}'

urlpatterns = [
    url(r'^about/$', views.AboutView.as_view(), name='about'),
    url(r'^gas-station/$', GasStationView.as_view(), name='gas-station'),
    url(r'^safes/$', views.SafeTransactionCreationView.as_view(), name='safes'),
    path('safes/<str:address>/funded/', views.SafeSignalView.as_view(), name='safe-signal'),
    path('safes/<str:address>/transactions/', views.SafeMultisigTxView.as_view(), name='safe-multisig-tx'),
    path('safes/<str:address>/transactions/estimate', views.SafeMultisigTxEstimateView.as_view(),
         name='safe-multisig-tx-estimate'),
]
