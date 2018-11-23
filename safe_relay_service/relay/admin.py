from django.contrib import admin

from .models import SafeContract, SafeCreation, SafeFunding, SafeMultisigTx


admin.site.register(SafeFunding)


@admin.register(SafeContract)
class SafeContractAdmin(admin.ModelAdmin):
    list_display = ('address', 'master_copy')


@admin.register(SafeCreation)
class SafeCreationAdmin(admin.ModelAdmin):
    list_display = ('safe', 'deployer', 'threshold', 'payment', 'payment_ether', 'payment_token')


@admin.register(SafeMultisigTx)
class SafeMultisigTxAdmin(admin.ModelAdmin):
    list_display = ('safe', 'to', 'value', 'nonce', 'data')
