from django.urls import path

from . import views_v2

app_name = "safe"

timestamp_regex = '\\d{4}[-]?\\d{1,2}[-]?\\d{1,2} \\d{1,2}:\\d{1,2}:\\d{1,2}'

urlpatterns = [
    path('safes/', views_v2.SafeCreationView.as_view(), name='safe-creation'),
    path('safes/<str:address>/funded/', views_v2.SafeSignalView.as_view(), name='safe-signal'),
]
