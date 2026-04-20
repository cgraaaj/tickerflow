"""Project-wide DRF exception handler.

Wraps DRF's default handler to enforce a consistent error envelope:

    {
        "error":         "<short machine-readable code>",
        "detail":        "<human-readable message>",
        "request_id":    "<uuid for log correlation>",
        "failed_indices": [...]   # only when handler attaches them
    }

A bare 500 (uncaught exception) used to leak Django's debug HTML or, in
prod, a generic ``"detail": "A server error occurred."``. Both make it
impossible for batch clients to recover at row-level. This handler:

* Always returns JSON.
* Always includes the current ``request_id`` so an operator can grep
  Loki / Sentry in seconds.
* Forwards ``exc.failed_indices`` (set by views that do per-item retry)
  so the client can fall back row-by-row instead of all-or-nothing.
* Emits the exception to Sentry (if installed) with the request-id as a
  tag so each incident is searchable.
"""

from __future__ import annotations

import logging
from typing import Any

from django.db import DatabaseError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_handler

from .observability import get_request_id

logger = logging.getLogger("tickerflow.exceptions")


def _attach(envelope: dict[str, Any], exc: Exception) -> dict[str, Any]:
    failed = getattr(exc, "failed_indices", None)
    if failed is not None:
        envelope["failed_indices"] = list(failed)
    partial = getattr(exc, "partial_results", None)
    if partial is not None:
        envelope["partial_results"] = partial
    return envelope


def structured_exception_handler(exc: Exception, context: dict[str, Any]) -> Response:
    request_id = get_request_id()
    response = drf_default_handler(exc, context)

    if response is not None:
        # Known DRF exception (validation, auth, throttle, etc.) — wrap it.
        original = response.data
        if isinstance(original, dict) and "detail" in original:
            detail = original.pop("detail")
            envelope: dict[str, Any] = {
                "error": exc.__class__.__name__,
                "detail": str(detail),
                "request_id": request_id,
            }
            if original:
                envelope["errors"] = original
        else:
            envelope = {
                "error": exc.__class__.__name__,
                "detail": original,
                "request_id": request_id,
            }
        response.data = _attach(envelope, exc)
        return response

    # Anything DRF didn't handle — DB driver errors, KeyError, etc.
    # These would otherwise become a bare 500 (or worse, an HTML page).
    if isinstance(exc, DatabaseError):
        code = "database_error"
        http_status = status.HTTP_503_SERVICE_UNAVAILABLE
    else:
        code = "internal_error"
        http_status = status.HTTP_500_INTERNAL_SERVER_ERROR

    logger.exception("unhandled exception in %s: %s", context.get("view"), exc)

    envelope = _attach(
        {
            "error": code,
            "detail": str(exc) or exc.__class__.__name__,
            "request_id": request_id,
        },
        exc,
    )
    return Response(envelope, status=http_status)
