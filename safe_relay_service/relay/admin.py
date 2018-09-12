from django.contrib import admin

from .models import SafeContract, SafeCreation, SafeFunding, SafeMultisigTx

admin.site.register([SafeContract, SafeCreation, SafeFunding, SafeMultisigTx])
