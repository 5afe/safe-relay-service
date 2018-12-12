from django.contrib import admin

from .models import PriceOracle, PriceOracleTicker, Token


@admin.register(PriceOracle)
class PriceOracleAdmin(admin.ModelAdmin):
    list_display = ('name', )


@admin.register(PriceOracleTicker)
class PriceOracleTicker(admin.ModelAdmin):
    list_display = ('price_oracle_name', 'token_symbol', 'ticker', 'inverse')

    def price_oracle_name(self, obj):
        return obj.price_oracle.name

    def token_symbol(self, obj):
        return obj.token.symbol

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('price_oracle', 'token')


@admin.register(Token)
class TokenAdmin(admin.ModelAdmin):
    list_display = ('address', 'name', 'symbol', 'decimals', 'fixed_eth_conversion', 'relevance', 'gas')
