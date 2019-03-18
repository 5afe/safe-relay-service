from django.conf.urls import include, url
from django.urls import path

from safe_relay_service.gas_station.views import GasStationView
from safe_relay_service.tokens.views import TokenView

from . import views

app_name = "safe"

timestamp_regex = '\\d{4}[-]?\\d{1,2}[-]?\\d{1,2} \\d{1,2}:\\d{1,2}:\\d{1,2}'

urlpatterns = [
    url(r'^about/$', views.AboutView.as_view(), name='about'),
    url(r'^gas-station/$', GasStationView.as_view(), name='gas-station'),
    url(r'^tokens/$', TokenView.as_view(), name='tokens'),
    url(r'^safes/$', views.SafeCreationView.as_view(), name='safes'),
    path('safes/<str:address>/', views.SafeView.as_view(), name='safe'),
    path('safes/lookup/<str:address>/', views.SafeLookupView.as_view(), name='safe-lookup'),
    path('safes/<str:address>/funded/', views.SafeSignalView.as_view(), name='safe-signal'),
    path('safes/<str:address>/transactions/', views.SafeMultisigTxView.as_view(), name='safe-multisig-tx'),
    path('safes/<str:address>/transactions/estimate/', views.SafeMultisigTxEstimateView.as_view(),
         name='safe-multisig-tx-estimate'),
    path('subscriptions/<str:address>/<str:flag>/', views.TxListView.as_view(), name='tx-list'),
    path('subscriptions/create/', views.SafeMultisigSubTxView.as_view(), name='safe-multisig-subtx'),
    path('subscriptions/execute/', views.SafeMultisigSubTxExecute.as_view(), name='safe-multisig-subtx-execute'),
]
