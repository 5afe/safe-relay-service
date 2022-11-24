from django.urls import path

from . import views_v3

app_name = "safe"

timestamp_regex = "\\d{4}[-]?\\d{1,2}[-]?\\d{1,2} \\d{1,2}:\\d{1,2}:\\d{1,2}"

urlpatterns = [
    path("safes/", views_v3.SafeCreationView.as_view(), name="safe-creation"),
    path(
        "safes/predict/",
        views_v3.SafeAddressPredictionView.as_view(),
        name="safe-address-prediction",
    ),
    path(
        "safes/estimates/",
        views_v3.SafeCreationEstimateView.as_view(),
        name="safe-creation-estimates",
    ),
]
