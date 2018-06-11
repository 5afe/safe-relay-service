from django.contrib import admin

from .models import SafeContract, SafeCreation, SafeFunding

admin.site.register([SafeContract, SafeCreation, SafeFunding])
