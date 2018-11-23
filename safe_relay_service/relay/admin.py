from django.contrib import admin

from .models import SafeContract, SafeCreation, SafeFunding, SafeMultisigTx


@admin.register(SafeContract)
class SafeContractAdmin(admin.ModelAdmin):
    list_display = ('address', 'master_copy')


@admin.register(SafeCreation)
class SafeCreationAdmin(admin.ModelAdmin):
    list_display = ('safe', 'deployer', 'threshold', 'payment', 'payment_ether', 'payment_token')


@admin.register(SafeFunding)
class SafeFundingAdmin(admin.ModelAdmin):
    list_display = ('safe', 'safe_status', 'deployer_funded_tx_hash', 'safe_deployed_tx_hash')

    def safe_status(self, obj: SafeFunding):
        return obj.__str__()


@admin.register(SafeMultisigTx)
class SafeMultisigTxAdmin(admin.ModelAdmin):
    list_display = ('safe', 'to', 'value', 'nonce', 'data')
