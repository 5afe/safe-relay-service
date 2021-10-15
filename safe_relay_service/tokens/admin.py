from django.contrib import admin

from .models import PriceOracle, PriceOracleTicker, Token
from .price_oracles import CannotGetTokenPriceFromApi


@admin.register(PriceOracle)
class PriceOracleAdmin(admin.ModelAdmin):
    list_display = ("name", "configuration")
    ordering = ("name",)


@admin.register(PriceOracleTicker)
class PriceOracleTickerAdmin(admin.ModelAdmin):
    list_display = ("token_symbol", "price_oracle_name", "ticker", "inverse", "price")
    list_filter = (("token", admin.RelatedOnlyFieldListFilter), "inverse")
    list_select_related = ("price_oracle", "token")
    search_fields = ["token__symbol", "=token__address", "price_oracle__name"]

    def price_oracle_name(self, obj):
        return obj.price_oracle.name

    def token_symbol(self, obj):
        return obj.token.symbol


@admin.register(Token)
class TokenAdmin(admin.ModelAdmin):
    list_display = (
        "relevance",
        "address",
        "name",
        "symbol",
        "decimals",
        "fixed_eth_conversion",
        "gas",
    )
    list_filter = ("gas", "decimals", "fixed_eth_conversion")
    ordering = ("relevance",)
    search_fields = ["symbol", "address", "name"]
    readonly_fields = ("eth_value", "price_oracle_ticker_pairs")

    def eth_value(self, obj: Token):
        if self.decimals is None:  # Add token admin page
            return 0.0
        try:
            return obj.get_eth_value()
        except CannotGetTokenPriceFromApi:
            return None

    def price_oracle_ticker_pairs(self, obj: Token):
        return [
            (price_oracle_ticker.price_oracle.name, price_oracle_ticker.ticker)
            for price_oracle_ticker in obj.price_oracle_tickers.all()
        ]
