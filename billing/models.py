import uuid

from django.conf import settings
from django.db import models


class UsageLedger(models.Model):
    """
    Immutable ledger recording every billable API call.
    One row per request -- units_consumed equals the number of data rows returned.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="usage_records",
        db_index=True,
    )
    api_key_prefix = models.CharField(max_length=8, blank=True, default="")
    endpoint = models.CharField(max_length=255)
    method = models.CharField(max_length=10, default="GET")
    units_consumed = models.IntegerField(default=0)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    query_ms = models.FloatField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "tickerflow_usage_ledger"
        ordering = ["-timestamp"]
        verbose_name = "usage record"
        verbose_name_plural = "usage records"
        indexes = [
            models.Index(fields=["user", "-timestamp"], name="idx_usage_user_ts"),
            models.Index(fields=["endpoint", "-timestamp"], name="idx_usage_endpoint_ts"),
        ]

    def __str__(self):
        return f"{self.user} | {self.endpoint} | {self.units_consumed} units"
