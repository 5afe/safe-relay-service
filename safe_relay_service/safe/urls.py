from django.conf.urls import url

from safe_relay_service.gas_station.views import GasStationView

from . import views

app_name = "safe"

timestamp_regex = '\\d{4}[-]?\\d{1,2}[-]?\\d{1,2} \\d{1,2}:\\d{1,2}:\\d{1,2}'

urlpatterns = [
    url(r'^about/$', views.AboutView.as_view(), name='about'),
    url(r'^gas-station/$', GasStationView.as_view(), name='gas-station'),
    url(r'^safes/$', views.SafeTransactionCreationView.as_view(), name='safes'),
]
