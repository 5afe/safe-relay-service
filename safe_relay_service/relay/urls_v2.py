from django.urls import path

from . import views_v2

app_name = "safe"

timestamp_regex = "\\d{4}[-]?\\d{1,2}[-]?\\d{1,2} \\d{1,2}:\\d{1,2}:\\d{1,2}"

urlpatterns = [
    path("safes/", views_v2.SafeCreationView.as_view(), name="safe-creation"),
    path(
        "safes/estimates/",
        views_v2.SafeCreationEstimateView.as_view(),
        name="safe-creation-estimates",
    ),
    path(
        "safes/<str:address>/transactions/estimate/",
        views_v2.SafeMultisigTxEstimateView.as_view(),
        name="safe-multisig-tx-estimate",
    ),
    path(
        "safes/<str:address>/funded/",
        views_v2.SafeSignalView.as_view(),
        name="safe-signal",
    ),
    path(
        "safes/<str:address>/organization/",
        views_v2.OrganizationSignalView.as_view(),
        name="organization-signal",
    ),
]
