import uuid

from rest_framework import serializers


INTERVAL_CHOICES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]

MAX_BATCH_INSTRUMENT_IDS = 50
MAX_BATCH_STOCK_IDS = 20


def _parse_csv_ints(raw: str, field_name: str, max_items: int) -> list[int]:
    """Parse a comma-separated string of integers with bounds checking."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) > max_items:
        raise serializers.ValidationError(
            {field_name: f"Maximum {max_items} values allowed, got {len(parts)}."}
        )
    parsed = []
    for p in parts:
        try:
            val = int(p)
            if val < 1:
                raise ValueError
            parsed.append(val)
        except (ValueError, TypeError):
            raise serializers.ValidationError(
                {field_name: f"'{p}' is not a valid positive integer."}
            )
    return parsed


def _parse_csv_uuids(raw: str, field_name: str, max_items: int) -> list[str]:
    """Parse a comma-separated string of UUIDs with bounds checking."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) > max_items:
        raise serializers.ValidationError(
            {field_name: f"Maximum {max_items} values allowed, got {len(parts)}."}
        )
    parsed = []
    for p in parts:
        try:
            uuid.UUID(p)
            parsed.append(p)
        except ValueError:
            raise serializers.ValidationError(
                {field_name: f"'{p}' is not a valid UUID."}
            )
    return parsed


def _parse_csv_strings(raw: str, field_name: str, max_items: int) -> list[str]:
    """Parse a comma-separated string of names with bounds checking."""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) > max_items:
        raise serializers.ValidationError(
            {field_name: f"Maximum {max_items} values allowed, got {len(parts)}."}
        )
    return parts


class TickQuerySerializer(serializers.Serializer):
    """
    Validate query parameters for the ticks endpoint.

    Supports single instrument via ``instrument_id`` or batch via
    ``instrument_ids`` (comma-separated, max 50).  The two params are
    mutually exclusive.
    """

    instrument_id = serializers.IntegerField(required=False, default=None, min_value=1)
    instrument_ids = serializers.CharField(required=False, default=None)
    start = serializers.DateTimeField(required=False, default=None)
    end = serializers.DateTimeField(required=False, default=None)
    limit = serializers.IntegerField(required=False, default=100, min_value=1, max_value=50000)
    offset = serializers.IntegerField(required=False, default=0, min_value=0)

    def validate(self, data):
        has_single = data.get("instrument_id") is not None
        has_batch = data.get("instrument_ids") is not None

        if has_single and has_batch:
            raise serializers.ValidationError(
                "Provide either 'instrument_id' or 'instrument_ids', not both."
            )
        if not has_single and not has_batch:
            raise serializers.ValidationError(
                "Either 'instrument_id' or 'instrument_ids' is required."
            )

        if has_batch:
            data["_instrument_id_list"] = _parse_csv_ints(
                data["instrument_ids"], "instrument_ids", MAX_BATCH_INSTRUMENT_IDS,
            )

        if data.get("start") and data.get("end"):
            if data["start"] >= data["end"]:
                raise serializers.ValidationError({"end": "end must be after start."})
        return data


class CandleQuerySerializer(serializers.Serializer):
    """Validate query parameters for the candles endpoint."""

    instrument_id = serializers.IntegerField(min_value=1)
    interval = serializers.ChoiceField(choices=INTERVAL_CHOICES)
    start = serializers.DateTimeField(required=False, default=None)
    end = serializers.DateTimeField(required=False, default=None)
    limit = serializers.IntegerField(required=False, default=500, min_value=1, max_value=5000)

    def validate(self, data):
        if data.get("start") and data.get("end"):
            if data["start"] >= data["end"]:
                raise serializers.ValidationError({"end": "end must be after start."})
        return data


class InstrumentQuerySerializer(serializers.Serializer):
    """
    Validate query parameters for the instruments endpoint.

    Supports single stock filter via ``stock_id`` / ``stock_name`` or batch
    via ``stock_ids`` (comma-separated UUIDs, max 20) / ``stock_names``
    (comma-separated, max 20).  Single and batch variants of the same
    field are mutually exclusive.
    """

    stock_id = serializers.UUIDField(required=False, default=None)
    stock_ids = serializers.CharField(required=False, default=None)
    stock_name = serializers.CharField(required=False, default=None)
    stock_names = serializers.CharField(required=False, default=None)
    instrument_type = serializers.ChoiceField(
        choices=["CE", "PE", "FUT"], required=False, default=None,
    )
    expiry = serializers.DateField(required=False, default=None)
    nearest_strike = serializers.FloatField(required=False, default=None)
    limit = serializers.IntegerField(required=False, default=50, min_value=1, max_value=2000)

    def validate(self, data):
        if data.get("stock_id") and data.get("stock_ids"):
            raise serializers.ValidationError(
                "Provide either 'stock_id' or 'stock_ids', not both."
            )
        if data.get("stock_name") and data.get("stock_names"):
            raise serializers.ValidationError(
                "Provide either 'stock_name' or 'stock_names', not both."
            )

        if data.get("stock_ids"):
            data["_stock_id_list"] = _parse_csv_uuids(
                data["stock_ids"], "stock_ids", MAX_BATCH_STOCK_IDS,
            )
        if data.get("stock_names"):
            data["_stock_name_list"] = _parse_csv_strings(
                data["stock_names"], "stock_names", MAX_BATCH_STOCK_IDS,
            )
        return data


class ExpiryQuerySerializer(serializers.Serializer):
    """Validate query parameters for the expiries endpoint."""

    instrument_type = serializers.ChoiceField(
        choices=["CE", "PE", "FUT"], required=False, default=None,
    )
