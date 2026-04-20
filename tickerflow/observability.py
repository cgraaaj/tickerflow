"""Cross-cutting observability primitives.

Currently exposes:

* ``RequestIDMiddleware`` — accepts an inbound ``X-Request-ID`` header (or
  generates a UUID4) and pins it to a contextvar so every log record emitted
  during the request, plus the response header, carries the same id.
* ``RequestIDFilter`` — a ``logging.Filter`` that reads from the contextvar
  and injects ``request_id`` onto every ``LogRecord`` so format strings can
  reference ``%(request_id)s`` even outside the request lifecycle.
"""

from __future__ import annotations

import contextvars
import logging
import uuid

REQUEST_ID_HEADER = "X-Request-ID"
_META_KEY = "HTTP_X_REQUEST_ID"

_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default="-"
)


def get_request_id() -> str:
    """Return the request-id for the current async/thread context."""
    return _request_id_ctx.get()


def set_request_id(value: str) -> contextvars.Token:
    """Bind a request-id to the current context (returns a token for reset)."""
    return _request_id_ctx.set(value)


class RequestIDFilter(logging.Filter):
    """Inject the contextvar ``request_id`` onto every LogRecord."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_ctx.get()
        return True


class RequestIDMiddleware:
    """Attach a stable request-id to every request/response/log line.

    Honours an inbound header so upstream proxies (Traefik, nginx) can chain
    a trace-id end-to-end. Also exposes the id on ``request.request_id`` so
    views/handlers can include it in error envelopes.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = request.META.get(_META_KEY, "").strip()
        rid = incoming or uuid.uuid4().hex
        token = set_request_id(rid)
        request.request_id = rid
        try:
            response = self.get_response(request)
        finally:
            _request_id_ctx.reset(token)
        response[REQUEST_ID_HEADER] = rid
        return response
