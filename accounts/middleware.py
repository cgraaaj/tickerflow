import re
from django.http import JsonResponse
from django.utils import timezone

from .models import APIKey
from .utils import hash_api_key

EXEMPT_PATTERNS = [
    re.compile(r"^/admin/"),
    re.compile(r"^/api/v1/health/"),
    re.compile(r"^/static/"),
]


class APIKeyAuthMiddleware:
    """
    Authenticate requests bearing an X-API-KEY header.

    Skips admin, health-check, and static paths. For all other /api/
    paths, a valid API key is required.

    Lookup strategy: use the unhashed prefix for a fast DB lookup,
    then verify the full SHA-256 hash.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if self._is_exempt(request.path):
            return self.get_response(request)

        if not request.path.startswith("/api/"):
            return self.get_response(request)

        raw_key = request.META.get("HTTP_X_API_KEY", "")
        if not raw_key:
            return JsonResponse(
                {"detail": "Authentication credentials were not provided."},
                status=401,
            )

        from django.conf import settings as conf

        prefix_len = getattr(conf, "API_KEY_PREFIX_LENGTH", 8)
        if len(raw_key) < prefix_len:
            return JsonResponse({"detail": "Invalid API key."}, status=401)

        prefix = raw_key[:prefix_len]
        hashed = hash_api_key(raw_key)

        try:
            api_key = APIKey.objects.select_related("user").get(
                prefix=prefix,
                hashed_key=hashed,
                is_active=True,
            )
        except APIKey.DoesNotExist:
            return JsonResponse({"detail": "Invalid API key."}, status=401)

        if not api_key.user.is_active:
            return JsonResponse({"detail": "User account is disabled."}, status=403)

        APIKey.objects.filter(pk=api_key.pk).update(last_used_at=timezone.now())

        request.user = api_key.user
        request.api_key = api_key

        return self.get_response(request)

    @staticmethod
    def _is_exempt(path: str) -> bool:
        return any(pattern.match(path) for pattern in EXEMPT_PATTERNS)
