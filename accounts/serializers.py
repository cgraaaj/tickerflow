from rest_framework import serializers

from .models import APIKey


class APIKeyCreateSerializer(serializers.Serializer):
    label = serializers.CharField(max_length=100, required=False, default="")


class APIKeyResponseSerializer(serializers.ModelSerializer):
    """Read-only serializer -- never exposes the hashed key."""

    class Meta:
        model = APIKey
        fields = ["id", "prefix", "label", "is_active", "created_at", "last_used_at"]
        read_only_fields = fields


class APIKeyCreatedSerializer(serializers.Serializer):
    """Returned once at creation time with the plaintext key."""

    id = serializers.UUIDField()
    key = serializers.CharField()
    prefix = serializers.CharField()
    label = serializers.CharField()
    created_at = serializers.DateTimeField()
