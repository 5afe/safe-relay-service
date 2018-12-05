from django.contrib import admin

from .models import GasPrice


@admin.register(GasPrice)
class GasPriceAdmin(admin.ModelAdmin):
    list_display = ('lowest', 'safe_low', 'standard', 'fast', 'fastest')
