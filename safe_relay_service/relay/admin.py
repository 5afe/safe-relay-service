from typing import Optional

from django.contrib import admin
from django.db.models.expressions import RawSQL

from web3 import Web3

from .models import (EthereumBlock, EthereumEvent, EthereumTx, InternalTx,
                     SafeContract, SafeCreation, SafeCreation2, SafeFunding,
                     SafeMultisigTx, SafeTxStatus)


class EthereumTxForeignClassMixinAdmin:
    """
    Common utilities for classes that have a `ForeignKey` to `EthereumTx`
    """
    list_select_related = ('ethereum_tx', 'ethereum_tx__block')
    ordering = ['-ethereum_tx__block__number']

    def get_search_results(self, request, queryset, search_term):
        # Fix tx_hash search
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        queryset |= self.model.objects.filter(ethereum_tx__tx_hash=search_term)
        return queryset, use_distinct

    def block_number(self, obj: EthereumEvent) -> Optional[int]:
        if obj.ethereum_tx.block:
            return obj.ethereum_tx.block.number


class EthereumEventListFilter(admin.SimpleListFilter):
    # Human-readable title which will be displayed in the
    # right admin sidebar just above the filter options.
    title = 'Event type'

    # Parameter for the filter that will be used in the URL query.
    parameter_name = 'event_type'

    def lookups(self, request, model_admin):
        return (
            ('ERC20', 'ERC20 Transfer'),
            ('ERC721', 'ERC721 Transfer'),
            ('OTHER', 'Other events'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'ERC20':
            return queryset.erc20_events()
        elif self.value() == 'ERC721':
            return queryset.erc721_events()
        elif self.value() == 'OTHER':
            return queryset.not_erc_20_721_events()


class EthereumEventFromToListFilter(admin.SimpleListFilter):
    title = 'Safe Users'
    parameter_name = 'event_from_to_safe'

    def lookups(self, request, model_admin):
        return (
            ('FROM_SAFE_USER', 'Transfers From Safe'),
            ('TO_SAFE_USER', 'Transfers To Safe'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'FROM_SAFE_USER':
            param = 'from'
        elif self.value() == 'TO_SAFE_USER':
            param = 'to'
        else:
            return

        # Django doesn't support `->>` for auto conversion to text
        return queryset.annotate(address=RawSQL("arguments->>%s", (param,))
                                 ).filter(address__in=SafeContract.objects.values('address'))


@admin.register(EthereumBlock)
class EthereumEventAdmin(admin.ModelAdmin):
    date_hierarchy = 'timestamp'
    list_display = ('number', 'timestamp', 'gas_limit', 'gas_used', 'block_hash')
    search_fields = ['=number']
    ordering = ['-number']


@admin.register(EthereumEvent)
class EthereumEventAdmin(EthereumTxForeignClassMixinAdmin, admin.ModelAdmin):
    list_display = ('block_number', 'ethereum_tx_id', 'log_index', 'erc20', 'erc721', 'from_', 'to', 'arguments')
    list_display_links = ('log_index', 'arguments')
    list_filter = (EthereumEventListFilter, EthereumEventFromToListFilter)
    search_fields = ['arguments']

    def from_(self, obj: EthereumEvent):
        return obj.arguments.get('from')

    def to(self, obj: EthereumEvent):
        return obj.arguments.get('to')

    def erc20(self, obj: EthereumEvent):
        return obj.is_erc20()

    def erc721(self, obj: EthereumEvent):
        return obj.is_erc721()

    # Fancy icons
    erc20.boolean = True
    erc721.boolean = True


@admin.register(EthereumTx)
class EthereumTxAdmin(admin.ModelAdmin):
    list_display = ('tx_hash', 'nonce', '_from', 'to')
    search_fields = ['=tx_hash', '=_from', '=to']

    def get_search_results(self, request, queryset, search_term):
        # Fix tx_hash search
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        queryset |= self.model.objects.filter(tx_hash=search_term)
        return queryset, use_distinct


@admin.register(InternalTx)
class InternalTxAdmin(EthereumTxForeignClassMixinAdmin, admin.ModelAdmin):
    list_display = ('block_number', 'ethereum_tx_id', '_from', 'to', 'value', 'call_type')
    list_filter = ('tx_type', 'call_type')
    search_fields = ['=ethereum_tx__block__number', '=_from', '=to']


class SafeContractDeployedListFilter(admin.SimpleListFilter):
    title = 'Deployed'
    parameter_name = 'deployed'

    def lookups(self, request, model_admin):
        return (
            ('NOT_DEPLOYED', 'Not deployed Safes'),
            ('DEPLOYED', 'Deployed Safes'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'NOT_DEPLOYED':
            return queryset.not_deployed()
        elif self.value() == 'DEPLOYED':
            return queryset.deployed()


class SafeContractBalanceListFilter(admin.SimpleListFilter):
    title = 'Balance'
    parameter_name = 'balance'

    def lookups(self, request, model_admin):
        return (
            ('HAS_BALANCE', 'Has some ether'),
            ('HAS_MORE_THAN_1_ETH', 'Has more than 1 ether'),
        )

    def queryset(self, request, queryset):
        if self.value() == 'HAS_BALANCE':
            return queryset.with_balance().filter(balance__gt=0)
        elif self.value() == 'HAS_MORE_THAN_1_ETH':
            return queryset.with_balance().filter(balance__gt=Web3.toWei(1, 'ether'))


class SafeContractTokensListFilter(admin.SimpleListFilter):
    title = 'Tokens'
    parameter_name = 'tokens'

    def lookups(self, request, model_admin):
        return (
            ('HAS_TOKENS', 'Safes with tokens'),
            ('NO_TOKENS', 'Safes without tokens'),
        )

    def queryset(self, request, queryset):
        events = EthereumEvent.objects.annotate(address=RawSQL("arguments->>'to'", ())
                                                ).values('address').distinct()
        if self.value() == 'HAS_TOKENS':
            return queryset.filter(address__in=events)
        elif self.value() == 'NO_TOKENS':
            return queryset.exclude(address__in=events)


@admin.register(SafeContract)
class SafeContractAdmin(admin.ModelAdmin):
    date_hierarchy = 'created'
    list_display = ('created', 'address', 'master_copy', 'balance')
    list_filter = ('master_copy', SafeContractDeployedListFilter,
                   SafeContractBalanceListFilter, SafeContractTokensListFilter)
    ordering = ['-created']
    search_fields = ['address']

    def get_queryset(self, request):
        return super().get_queryset(request).with_balance()

    def balance(self, obj):
        return obj.balance


@admin.register(SafeCreation)
class SafeCreationAdmin(admin.ModelAdmin):
    date_hierarchy = 'created'
    list_display = ('created', 'safe_id', 'deployer', 'threshold', 'payment', 'payment_token', 'ether_deploy_cost', )
    list_filter = ('safe__master_copy', 'threshold', 'payment_token')
    search_fields = ['=safe__address', '=deployer', 'owners']

    def ether_deploy_cost(self, obj: SafeCreation):
        return Web3.fromWei(obj.wei_deploy_cost(), 'ether')


@admin.register(SafeCreation2)
class SafeCreation2Admin(admin.ModelAdmin):
    date_hierarchy = 'created'
    list_display = ('created', 'safe', 'threshold', 'payment', 'payment_token', 'ether_deploy_cost', )
    list_filter = ('safe__master_copy', 'threshold', 'payment_token')
    search_fields = ['=safe__address', 'owners']

    def ether_deploy_cost(self, obj: SafeCreation):
        return Web3.fromWei(obj.wei_estimated_deploy_cost(), 'ether')


@admin.register(SafeFunding)
class SafeFundingAdmin(admin.ModelAdmin):
    list_display = ('safe_id', 'safe_status', 'deployer_funded_tx_hash', 'safe_deployed_tx_hash')
    list_filter = ('safe_funded', 'deployer_funded', 'safe_deployed')
    search_fields = ['=safe__address']

    def safe_status(self, obj: SafeFunding):
        return obj.status()


@admin.register(SafeMultisigTx)
class SafeMultisigTxAdmin(admin.ModelAdmin):
    list_display = ('safe_id', 'ethereum_tx_id', 'to', 'value', 'nonce', 'data')
    list_filter = ('operation',)
    search_fields = ['=safe__address', '=ethereum_tx__tx_hash', 'to']


@admin.register(SafeTxStatus)
class SafeTxStatusAdmin(admin.ModelAdmin):
    list_display = ('safe_id', 'initial_block_number', 'tx_block_number', 'erc_20_block_number')
    search_fields = ['=safe__address']
