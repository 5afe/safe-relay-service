from django.contrib import admin

from web3 import Web3

from .models import SafeContract, SafeCreation, SafeFunding, SafeMultisigTx


@admin.register(SafeContract)
class SafeContractAdmin(admin.ModelAdmin):
    list_display = ('created', 'address', 'master_copy')


@admin.register(SafeCreation)
class SafeCreationAdmin(admin.ModelAdmin):
    list_display = ('created', 'safe', 'deployer', 'threshold', 'payment', 'payment_token', 'ether_deploy_cost', )

    def ether_deploy_cost(self, obj: SafeCreation):
        return Web3.fromWei(obj.wei_deploy_cost(), 'ether')


@admin.register(SafeFunding)
class SafeFundingAdmin(admin.ModelAdmin):
    list_display = ('safe', 'safe_status', 'deployer_funded_tx_hash', 'safe_deployed_tx_hash')

    def safe_status(self, obj: SafeFunding):
        return obj.status()


@admin.register(SafeMultisigTx)
class SafeMultisigTxAdmin(admin.ModelAdmin):
    list_display = ('safe', 'to', 'value', 'nonce', 'data')
