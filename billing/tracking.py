"""
Usage tracking mixin for DRF views.

Wraps dispatch() to:
1. Pre-check: reject if user balance is insufficient (HTTP 402)
2. Execute the view
3. Post-check: count rows returned, deduct from balance atomically,
   and record a UsageLedger entry
"""

import logging
from decimal import Decimal

from django.db.models import F
from django.http import JsonResponse

from accounts.models import CustomUser
from .models import UsageLedger

logger = logging.getLogger("billing.tracking")

COST_PER_UNIT = Decimal("1.00")
MIN_BALANCE_REQUIRED = Decimal("1.00")


class UsageTrackingMixin:
    """
    Add to any DRF APIView to enable usage-based billing.

    The mixin counts the number of rows in response.data["results"]
    (or response.data["count"]) and deducts that from the user's balance.
    """

    def dispatch(self, request, *args, **kwargs):
        user = getattr(request, "user", None)
        api_key = getattr(request, "api_key", None)

        is_internal = (
            user
            and hasattr(user, "tier")
            and not user.is_anonymous
            and user.tier == "internal"
        )

        if not is_internal and user and hasattr(user, "balance") and not user.is_anonymous:
            if user.balance < MIN_BALANCE_REQUIRED:
                return JsonResponse(
                    {
                        "detail": "Insufficient balance. Please top up your account.",
                        "balance": str(user.balance),
                    },
                    status=402,
                )

        response = super().dispatch(request, *args, **kwargs)

        drf_request = getattr(self, "request", request)
        user = getattr(drf_request, "user", None)

        if user is None or not hasattr(user, "balance") or user.is_anonymous:
            return response

        if response.status_code >= 400:
            return response

        units = self._count_units(response)
        api_key_prefix = api_key.prefix if api_key else ""

        query_ms = None
        if hasattr(response, "data") and isinstance(response.data, dict):
            query_ms = response.data.get("query_ms")

        if is_internal:
            UsageLedger.objects.create(
                user=user,
                api_key_prefix=api_key_prefix,
                endpoint=drf_request.path,
                method=drf_request.method,
                units_consumed=units,
                balance_after=user.balance,
                query_ms=query_ms,
            )
            logger.info(
                "usage [internal] user=%s endpoint=%s units=%d (no charge)",
                user.email, drf_request.path, units,
            )
        else:
            cost = units * COST_PER_UNIT
            CustomUser.objects.filter(pk=user.pk).update(balance=F("balance") - cost)
            user.refresh_from_db(fields=["balance"])

            UsageLedger.objects.create(
                user=user,
                api_key_prefix=api_key_prefix,
                endpoint=drf_request.path,
                method=drf_request.method,
                units_consumed=units,
                balance_after=user.balance,
                query_ms=query_ms,
            )
            logger.info(
                "usage user=%s endpoint=%s units=%d cost=%s balance_after=%s",
                user.email, drf_request.path, units, cost, user.balance,
            )

        return response

    @staticmethod
    def _count_units(response) -> int:
        """Extract the row count from a standard API response."""
        if not hasattr(response, "data") or not isinstance(response.data, dict):
            return 1

        results = response.data.get("results")
        if isinstance(results, list):
            return len(results)

        count = response.data.get("count")
        if isinstance(count, int):
            return count

        return 1
