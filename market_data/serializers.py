from rest_framework import serializers


INTERVAL_CHOICES = ["1m", "5m", "15m", "30m", "1h", "4h", "1d"]


class TickQuerySerializer(serializers.Serializer):
    """Validate query parameters for the ticks endpoint."""

    instrument_id = serializers.IntegerField(min_value=1)
    start = serializers.DateTimeField(required=False, default=None)
    end = serializers.DateTimeField(required=False, default=None)
    limit = serializers.IntegerField(required=False, default=100, min_value=1, max_value=10000)
    offset = serializers.IntegerField(required=False, default=0, min_value=0)

    def validate(self, data):
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
    """Validate query parameters for the instruments endpoint."""

    stock_id = serializers.UUIDField(required=False, default=None)
    stock_name = serializers.CharField(required=False, default=None)
    instrument_type = serializers.ChoiceField(
        choices=["CE", "PE", "FUT"], required=False, default=None,
    )
    expiry = serializers.DateField(required=False, default=None)
    nearest_strike = serializers.FloatField(required=False, default=None)
    limit = serializers.IntegerField(required=False, default=50, min_value=1, max_value=500)


class ExpiryQuerySerializer(serializers.Serializer):
    """Validate query parameters for the expiries endpoint."""

    instrument_type = serializers.ChoiceField(
        choices=["CE", "PE", "FUT"], required=False, default=None,
    )
