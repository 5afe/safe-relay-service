from django.contrib import admin

from web3 import Web3

from .models import (EthereumEvent, EthereumTx, InternalTx, SafeContract,
                     SafeCreation, SafeCreation2, SafeFunding, SafeMultisigTx,
                     SafeTxStatus)


@admin.register(SafeContract)
class SafeContractAdmin(admin.ModelAdmin):
    list_display = ('created', 'address', 'master_copy')


@admin.register(SafeCreation)
class SafeCreationAdmin(admin.ModelAdmin):
    list_display = ('created', 'safe', 'deployer', 'threshold', 'payment', 'payment_token', 'ether_deploy_cost', )

    def ether_deploy_cost(self, obj: SafeCreation):
        return Web3.fromWei(obj.wei_deploy_cost(), 'ether')


@admin.register(SafeCreation2)
class SafeCreationAdmin(admin.ModelAdmin):
    list_display = ('created', 'safe', 'threshold', 'payment', 'payment_token', 'ether_deploy_cost', )

    def ether_deploy_cost(self, obj: SafeCreation):
        return Web3.fromWei(obj.wei_estimated_deploy_cost(), 'ether')


@admin.register(SafeFunding)
class SafeFundingAdmin(admin.ModelAdmin):
    list_display = ('safe', 'safe_status', 'deployer_funded_tx_hash', 'safe_deployed_tx_hash')

    def safe_status(self, obj: SafeFunding):
        return obj.status()


@admin.register(EthereumTx)
class EthereumTxAdmin(admin.ModelAdmin):
    list_display = ('tx_hash', 'nonce', 'to', '_from')


@admin.register(SafeMultisigTx)
class SafeMultisigTxAdmin(admin.ModelAdmin):
    list_display = ('safe', 'to', 'value', 'nonce', 'data')


@admin.register(InternalTx)
class InternalTxAdmin(admin.ModelAdmin):
    list_display = ('ethereum_tx', '_from', 'to', 'value', 'call_type')


@admin.register(EthereumEvent)
class EthereumEventAdmin(admin.ModelAdmin):
    list_display = ('ethereum_tx', 'log_index', 'erc20', 'erc721', 'arguments')

    def erc20(self, obj: EthereumEvent):
        return obj.is_erc20()

    def erc721(self, obj: EthereumEvent):
        return obj.is_erc721()


@admin.register(SafeTxStatus)
class SafeMultisigTxAdmin(admin.ModelAdmin):
    list_display = ('safe', 'initial_block_number', 'tx_block_number', 'erc_20_block_number')
