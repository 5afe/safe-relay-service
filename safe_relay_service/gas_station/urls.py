from django.urls import path

from . import views

app_name = "gas_station"

urlpatterns = [
    path("", views.GasStationView.as_view(), name="gas-station"),
]
