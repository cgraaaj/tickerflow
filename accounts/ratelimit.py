"""
Redis-based rate limiting middleware.

Uses a fixed-window counter per API key with TTL expiry.
Tier-based limits are read from settings.RATE_LIMITS.
Degrades gracefully if Redis is unavailable (allows traffic through).
"""

import logging
import time

import redis
from django.conf import settings
from django.http import JsonResponse

logger = logging.getLogger("accounts.ratelimit")

_redis_client = None
_redis_available = None


def _get_redis():
    """Lazy-init Redis connection with connection pooling."""
    global _redis_client, _redis_available
    if _redis_client is not None:
        return _redis_client if _redis_available else None

    try:
        _redis_client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=1,
        )
        _redis_client.ping()
        _redis_available = True
        logger.info("Redis connected: %s", settings.REDIS_URL)
        return _redis_client
    except Exception as exc:
        _redis_available = False
        logger.warning("Redis unavailable (%s), rate limiting disabled: %s", settings.REDIS_URL, exc)
        return None


class RateLimitMiddleware:
    """
    Per-API-key rate limiting using Redis INCR + EXPIRE.

    Runs after APIKeyAuthMiddleware so request.api_key and request.user
    are already set. Skips requests without an API key (admin, health, etc).

    Response headers on every request:
        X-RateLimit-Limit:     max requests per window
        X-RateLimit-Remaining: requests left in current window
        X-RateLimit-Reset:     seconds until window resets

    On limit exceeded: HTTP 429 with Retry-After header.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        api_key = getattr(request, "api_key", None)
        user = getattr(request, "user", None)

        if not api_key or not user or not hasattr(user, "tier"):
            return self.get_response(request)

        r = _get_redis()
        if r is None:
            return self.get_response(request)

        tier = getattr(user, "tier", "basic")
        limits = getattr(settings, "RATE_LIMITS", {})
        max_requests = limits.get(tier, limits.get("basic", 60))
        window = getattr(settings, "RATE_LIMIT_WINDOW_SECONDS", 60)

        cache_key = f"rl:{api_key.prefix}:{int(time.time()) // window}"

        try:
            pipe = r.pipeline()
            pipe.incr(cache_key)
            pipe.expire(cache_key, window)
            results = pipe.execute()
            current_count = results[0]
        except redis.RedisError as exc:
            logger.warning("Redis error during rate limit check: %s", exc)
            return self.get_response(request)

        remaining = max(0, max_requests - current_count)
        reset_at = window - (int(time.time()) % window)

        if current_count > max_requests:
            response = JsonResponse(
                {
                    "detail": "Rate limit exceeded. Please slow down.",
                    "limit": max_requests,
                    "window_seconds": window,
                    "retry_after": reset_at,
                },
                status=429,
            )
            response["Retry-After"] = str(reset_at)
            response["X-RateLimit-Limit"] = str(max_requests)
            response["X-RateLimit-Remaining"] = "0"
            response["X-RateLimit-Reset"] = str(reset_at)
            return response

        response = self.get_response(request)
        response["X-RateLimit-Limit"] = str(max_requests)
        response["X-RateLimit-Remaining"] = str(remaining)
        response["X-RateLimit-Reset"] = str(reset_at)
        return response
