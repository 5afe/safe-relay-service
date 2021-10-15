from django.contrib import admin

from .models import GasPrice


@admin.register(GasPrice)
class GasPriceAdmin(admin.ModelAdmin):
    date_hierarchy = "created"
    list_display = ("created", "lowest", "safe_low", "standard", "fast", "fastest")
    ordering = ["-created"]
