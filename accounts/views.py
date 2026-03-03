from django.db import connection
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import APIKey
from .serializers import (
    APIKeyCreatedSerializer,
    APIKeyCreateSerializer,
    APIKeyResponseSerializer,
)
from .utils import generate_api_key


class APIKeyListCreateView(APIView):
    """List a user's API keys or create a new one."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        keys = APIKey.objects.filter(user=request.user).order_by("-created_at")
        serializer = APIKeyResponseSerializer(keys, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = APIKeyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        plaintext, prefix, hashed = generate_api_key()
        api_key = APIKey.objects.create(
            user=request.user,
            prefix=prefix,
            hashed_key=hashed,
            label=serializer.validated_data.get("label", ""),
        )

        return Response(
            APIKeyCreatedSerializer(
                {
                    "id": api_key.id,
                    "key": plaintext,
                    "prefix": prefix,
                    "label": api_key.label,
                    "created_at": api_key.created_at,
                }
            ).data,
            status=status.HTTP_201_CREATED,
        )


class APIKeyRevokeView(APIView):
    """Deactivate an API key."""

    permission_classes = [IsAuthenticated]

    def post(self, request, key_id):
        try:
            api_key = APIKey.objects.get(id=key_id, user=request.user)
        except APIKey.DoesNotExist:
            return Response(
                {"detail": "API key not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        api_key.is_active = False
        api_key.save(update_fields=["is_active"])
        return Response({"detail": "API key revoked."})


class LivenessView(APIView):
    """Liveness probe — confirms the process is alive. No external deps."""

    permission_classes = []
    authentication_classes = []

    def get(self, request):
        return Response({"status": "alive"})


class ReadinessView(APIView):
    """Readiness probe — confirms DB is reachable before accepting traffic."""

    permission_classes = []
    authentication_classes = []

    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            return Response({"status": "ready", "database": "ok"})
        except Exception as exc:
            return Response(
                {"status": "not_ready", "database": str(exc)},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
