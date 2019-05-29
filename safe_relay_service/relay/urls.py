from django.conf.urls import include, url
from django.urls import path

from rest_framework.authtoken import views as rest_views

from safe_relay_service.gas_station.views import GasStationView
from safe_relay_service.tokens.views import TokenView

from . import views

app_name = "safe"

timestamp_regex = '\\d{4}[-]?\\d{1,2}[-]?\\d{1,2} \\d{1,2}:\\d{1,2}:\\d{1,2}'

urlpatterns = [
    path('about/', views.AboutView.as_view(), name='about'),
    path('gas-station/', GasStationView.as_view(), name='gas-station'),
    path('tokens/', TokenView.as_view(), name='tokens'),
    path('safes/', views.SafeCreationView.as_view(), name='safe-creation'),
    path('safes/estimate/', views.SafeCreationEstimateView.as_view(), name='safe-creation-estimate'),
    path('safes/<str:address>/', views.SafeView.as_view(), name='safe'),
    path('safes/<str:address>/funded/', views.SafeSignalView.as_view(), name='safe-signal'),
    path('safes/<str:address>/transactions/', views.SafeMultisigTxView.as_view(), name='safe-multisig-txs'),
    path('safes/<str:address>/erc20-transactions/', views.ERC20View.as_view(), name='erc20-txs'),
    path('safes/<str:address>/erc721-transactions/', views.ERC721View.as_view(), name='erc721-txs'),
    path('safes/<str:address>/internal-transactions/', views.InternalTxsView.as_view(), name='internal-txs'),
    path('safes/<str:address>/all-transactions/', views.EthereumTxView.as_view(), name='safe-all-txs'),
    path('safes/<str:address>/transactions/estimate/', views.SafeMultisigTxEstimateView.as_view(),
         name='safe-multisig-tx-estimate'),
    path('safes/<str:address>/transactions/estimates/', views.SafeMultisigTxEstimatesView.as_view(),
         name='safe-multisig-tx-estimates'),
    path('private/api-token-auth/', rest_views.obtain_auth_token, name='api-token-auth'),
    path('private/safes/', views.PrivateSafesView.as_view(), name='private-safes'),
]
