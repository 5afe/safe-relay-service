from django.conf import settings
from django.urls import path

from safe_relay_service.tokens.models import Token
from . import views

app_name = "tokens"

urlpatterns = [
    path('', views.TokensView.as_view(), name='tokens'),
]

if settings.SAFE_DEFAULT_TOKEN_ADDRESS:
    Token.objects.create(
        address=settings.SAFE_DEFAULT_TOKEN_ADDRESS,
        name=settings.SAFE_DEFAULT_TOKEN_NAME,
        symbol=settings.SAFE_DEFAULT_TOKEN_SYMBOL,
        decimals=settings.SAFE_DEFAULT_TOKEN_DECIMALS
    )
