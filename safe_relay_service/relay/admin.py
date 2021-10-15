from typing import List, Optional

from django.contrib import admin
from django.db.models.expressions import RawSQL

from web3 import Web3

from .models import (
    BannedSigner,
    EthereumBlock,
    EthereumEvent,
    EthereumTx,
    SafeContract,
    SafeCreation,
    SafeCreation2,
    SafeFunding,
    SafeMultisigTx,
    SafeTxStatus,
)


class EthereumTxForeignClassMixinAdmin:
    """
    Common utilities for classes that have a `ForeignKey` to `EthereumTx`
    """

    list_select_related = ("ethereum_tx", "ethereum_tx__block")
    ordering = ["-ethereum_tx__block__number"]
    raw_id_fields = ("ethereum_tx",)

    def get_search_results(self, request, queryset, search_term):
        # Fix tx_hash search
        queryset, use_distinct = super().get_search_results(
            request, queryset, search_term
        )
        queryset |= self.model.objects.filter(ethereum_tx__tx_hash=search_term)
        return queryset, use_distinct

    def block_number(self, obj: EthereumEvent) -> Optional[int]:
        if obj.ethereum_tx.block:
            return obj.ethereum_tx.block.number


class EthereumEventListFilter(admin.SimpleListFilter):
    # Human-readable title which will be displayed in the
    # right admin sidebar just above the filter options.
    title = "Event type"

    # Parameter for the filter that will be used in the URL query.
    parameter_name = "event_type"

    def lookups(self, request, model_admin):
        return (
            ("ERC20", "ERC20 Transfer"),
            ("ERC721", "ERC721 Transfer"),
            ("OTHER", "Other events"),
        )

    def queryset(self, request, queryset):
        if self.value() == "ERC20":
            return queryset.erc20_events()
        elif self.value() == "ERC721":
            return queryset.erc721_events()
        elif self.value() == "OTHER":
            return queryset.not_erc_20_721_events()


class EthereumEventFromToListFilter(admin.SimpleListFilter):
    title = "Safe Users"
    parameter_name = "event_from_to_safe"

    def lookups(self, request, model_admin):
        return (
            ("FROM_SAFE_USER", "Transfers From Safe"),
            ("TO_SAFE_USER", "Transfers To Safe"),
        )

    def queryset(self, request, queryset):
        if self.value() == "FROM_SAFE_USER":
            param = "from"
        elif self.value() == "TO_SAFE_USER":
            param = "to"
        else:
            return

        # Django doesn't support `->>` for auto conversion to text
        return queryset.annotate(address=RawSQL("arguments->>%s", (param,))).filter(
            address__in=SafeContract.objects.values("address")
        )


@admin.register(EthereumBlock)
class EthereumBlockAdmin(admin.ModelAdmin):
    date_hierarchy = "timestamp"
    list_display = ("number", "timestamp", "gas_limit", "gas_used", "block_hash")
    search_fields = ["=number"]
    ordering = ["-number"]


@admin.register(EthereumEvent)
class EthereumEventAdmin(EthereumTxForeignClassMixinAdmin, admin.ModelAdmin):
    list_display = (
        "block_number",
        "ethereum_tx_id",
        "log_index",
        "erc20",
        "erc721",
        "from_",
        "to",
        "arguments",
    )
    list_display_links = ("log_index", "arguments")
    list_filter = (EthereumEventListFilter, EthereumEventFromToListFilter)
    search_fields = ["arguments"]

    def from_(self, obj: EthereumEvent):
        return obj.arguments.get("from")

    def to(self, obj: EthereumEvent):
        return obj.arguments.get("to")

    @admin.display(boolean=True)
    def erc20(self, obj: EthereumEvent):
        return obj.is_erc20()

    @admin.display(boolean=True)
    def erc721(self, obj: EthereumEvent):
        return obj.is_erc721()


@admin.register(EthereumTx)
class EthereumTxAdmin(admin.ModelAdmin):
    list_display = ("block_id", "tx_hash", "nonce", "_from", "to")
    list_filter = ("status",)
    ordering = ["-block_id"]
    raw_id_fields = ("block",)
    search_fields = ["=tx_hash", "=_from", "=to"]

    def get_search_results(self, request, queryset, search_term):
        # Fix tx_hash search
        queryset, use_distinct = super().get_search_results(
            request, queryset, search_term
        )
        queryset |= self.model.objects.filter(tx_hash=search_term)
        return queryset, use_distinct


class SafeContractDeployedListFilter(admin.SimpleListFilter):
    title = "Deployed"
    parameter_name = "deployed"

    def lookups(self, request, model_admin):
        return (
            ("NOT_DEPLOYED", "Not deployed Safes"),
            ("DEPLOYED", "Deployed Safes"),
        )

    def queryset(self, request, queryset):
        if self.value() == "NOT_DEPLOYED":
            return queryset.not_deployed()
        elif self.value() == "DEPLOYED":
            return queryset.deployed()


class SafeContractTokensListFilter(admin.SimpleListFilter):
    title = "Tokens"
    parameter_name = "tokens"

    def lookups(self, request, model_admin):
        return (
            ("HAS_TOKENS", "Safes with tokens"),
            ("NO_TOKENS", "Safes without tokens"),
        )

    def queryset(self, request, queryset):
        events = (
            EthereumEvent.objects.annotate(address=RawSQL("arguments->>'to'", ()))
            .values("address")
            .distinct()
        )
        if self.value() == "HAS_TOKENS":
            return queryset.filter(address__in=events)
        elif self.value() == "NO_TOKENS":
            return queryset.exclude(address__in=events)


@admin.register(SafeContract)
class SafeContractAdmin(admin.ModelAdmin):
    date_hierarchy = "created"
    list_display = ("created", "address", "master_copy")
    list_filter = (
        "master_copy",
        SafeContractDeployedListFilter,
        SafeContractTokensListFilter,
    )
    ordering = ["-created"]
    search_fields = ["address"]


@admin.register(SafeCreation)
class SafeCreationAdmin(admin.ModelAdmin):
    date_hierarchy = "created"
    list_display = (
        "created",
        "safe_id",
        "deployer",
        "threshold",
        "payment",
        "payment_token",
        "ether_deploy_cost",
    )
    list_filter = ("safe__master_copy", "threshold", "payment_token")
    ordering = ["-created"]
    raw_id_fields = ("safe",)
    search_fields = ["=safe__address", "=deployer", "owners"]

    def ether_deploy_cost(self, obj: SafeCreation) -> float:
        return Web3.fromWei(obj.wei_deploy_cost(), "ether")


class SafeCreation2DeployedListFilter(admin.SimpleListFilter):
    title = "Deployment transaction sent"
    parameter_name = "deployment"

    def lookups(self, request, model_admin):
        return (
            ("YES", "Safes with deployment transaction sent"),
            ("NO", "Safes without deployment transaction sent"),
        )

    def queryset(self, request, queryset):
        if self.value() == "YES":
            return queryset.exclude(tx_hash=None)
        elif self.value() == "NO":
            return queryset.filter(tx_hash=None)


@admin.register(SafeCreation2)
class SafeCreation2Admin(admin.ModelAdmin):
    date_hierarchy = "created"
    list_display = (
        "created",
        "safe",
        "threshold",
        "payment",
        "payment_token",
        "ether_deploy_cost",
    )
    list_filter = (
        SafeCreation2DeployedListFilter,
        "threshold",
        "safe__master_copy",
        "payment_token",
    )
    ordering = ["-created"]
    raw_id_fields = ("safe",)
    readonly_fields = ("gas_estimated", "gas_used")
    search_fields = ["=safe__address", "owners", "=tx_hash"]

    def ether_deploy_cost(self, obj: SafeCreation2) -> float:
        return Web3.fromWei(obj.wei_estimated_deploy_cost(), "ether")

    def gas_used(self, obj: SafeCreation2) -> Optional[int]:
        return obj.gas_used()


@admin.register(SafeFunding)
class SafeFundingAdmin(admin.ModelAdmin):
    list_display = (
        "safe_id",
        "safe_status",
        "deployer_funded_tx_hash",
        "safe_deployed_tx_hash",
    )
    list_filter = ("safe_funded", "deployer_funded", "safe_deployed")
    raw_id_fields = ("safe",)
    search_fields = ["=safe__address"]

    def safe_status(self, obj: SafeFunding) -> str:
        return obj.status()


class SafeMultisigTxStatusListFilter(admin.SimpleListFilter):
    # Human-readable title which will be displayed in the
    # right admin sidebar just above the filter options.
    title = "Status"

    # Parameter for the filter that will be used in the URL query.
    parameter_name = "status"

    def lookups(self, request, model_admin):
        return (
            ("SUCCESS", "Successful"),
            ("FAILED", "Failed"),
            ("NOT_FAILED", "Successful or not mined"),
            ("NOT_MINED", "Not mined"),
        )

    def queryset(self, request, queryset):
        if self.value() == "SUCCESS":
            return queryset.successful()
        elif self.value() == "FAILED":
            return queryset.failed()
        elif self.value() == "NOT_FAILED":
            return queryset.not_failed()
        elif self.value() == "NOT_MINED":
            return queryset.pending()


@admin.register(SafeMultisigTx)
class SafeMultisigTxAdmin(admin.ModelAdmin):
    date_hierarchy = "created"
    list_display = (
        "created",
        "safe_id",
        "nonce",
        "ethereum_tx_id",
        "refund_benefit_eth",
        "to",
        "value",
        "status",
        "signers",
    )
    list_filter = ("operation", SafeMultisigTxStatusListFilter)
    list_select_related = ("ethereum_tx",)
    ordering = ["-created"]
    raw_id_fields = ("safe", "ethereum_tx")
    readonly_fields = ("status", "signers")
    search_fields = ["=safe__address", "=ethereum_tx__tx_hash", "to"]

    def refund_benefit_eth(self, obj: SafeMultisigTx) -> Optional[float]:
        if (refund_benefit := obj.refund_benefit()) is not None:
            refund_benefit_eth = Web3.fromWei(abs(refund_benefit), "ether") * (
                -1 if refund_benefit < 0 else 1
            )
            return "{:.5f}".format(refund_benefit_eth)

    def status(self, obj: SafeMultisigTx) -> Optional[int]:
        if obj.ethereum_tx:
            return obj.ethereum_tx.status

    def signers(self, obj: SafeMultisigTx) -> List[str]:
        return obj.signers()


@admin.register(SafeTxStatus)
class SafeTxStatusAdmin(admin.ModelAdmin):
    list_display = (
        "safe_id",
        "initial_block_number",
        "tx_block_number",
        "erc_20_block_number",
    )
    raw_id_fields = ("safe",)
    search_fields = ["=safe__address"]


@admin.register(BannedSigner)
class BannedSignerAdmin(admin.ModelAdmin):
    list_display = ("address",)
    search_fields = ["=address"]
