"""
DRF authentication backend that trusts the user already set by
APIKeyAuthMiddleware on the Django HttpRequest.

DRF's dispatch() creates its own Request wrapper and re-authenticates
using its configured authentication classes. Without this backend,
DRF would overwrite the middleware-set user with AnonymousUser.
"""

from rest_framework.authentication import BaseAuthentication


class APIKeyMiddlewareAuthentication(BaseAuthentication):
    """
    Reads the user and api_key set by accounts.middleware.APIKeyAuthMiddleware
    on the original Django HttpRequest.
    """

    def authenticate(self, request):
        django_request = request._request
        user = getattr(django_request, "user", None)
        api_key = getattr(django_request, "api_key", None)

        if user and user.is_authenticated and api_key:
            return (user, api_key)

        return None
