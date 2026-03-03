from django.contrib import admin
from django.db.models import Sum, Count
from django.utils.html import format_html

from .models import UsageLedger


@admin.register(UsageLedger)
class UsageLedgerAdmin(admin.ModelAdmin):
    list_display = (
        "timestamp",
        "user",
        "api_key_prefix",
        "endpoint",
        "units_consumed",
        "balance_after",
        "query_ms_display",
    )
    list_filter = ("endpoint", "method", "timestamp")
    search_fields = ("user__email", "api_key_prefix", "endpoint")
    readonly_fields = (
        "id", "user", "api_key_prefix", "endpoint", "method",
        "units_consumed", "balance_after", "query_ms", "timestamp",
    )
    ordering = ("-timestamp",)
    date_hierarchy = "timestamp"
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Query (ms)")
    def query_ms_display(self, obj):
        if obj.query_ms is not None:
            color = "green" if obj.query_ms < 100 else "orange" if obj.query_ms < 500 else "red"
            return format_html('<span style="color: {};">{:.1f}</span>', color, obj.query_ms)
        return "-"
