from django.urls import path

from . import views

app_name = "tokens"

urlpatterns = [
    path('', views.TokenView.as_view(), name='tokens'),
]
