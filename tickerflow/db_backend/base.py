"""
Custom PostgreSQL backend that re-reads credentials from a Vault Agent
secrets file on every new connection, so dynamic DB credentials survive
lease rotation without a pod restart.

Falls back to the standard ``settings.DATABASES`` values when the file
is absent (local development, CI, etc.).
"""

import logging
import os
import re

from django.conf import settings
from django.db.backends.postgresql import base

logger = logging.getLogger("tickerflow.db_backend")

_VAULT_CREDS_PATH = getattr(settings, "VAULT_DB_CREDS_PATH", "/vault/secrets/db-creds")
_EXPORT_RE = re.compile(r'^export\s+(\w+)=["\']?(.*?)["\']?\s*$')

_cached_mtime: float | None = None
_cached_creds: dict[str, str] = {}


def _read_vault_creds() -> dict[str, str]:
    """
    Parse the Vault-injected shell file and return a dict of exported vars.

    Caches the result and only re-reads when the file's mtime changes,
    keeping per-request overhead near zero while still picking up rotations.
    """
    global _cached_mtime, _cached_creds

    path = _VAULT_CREDS_PATH
    if not os.path.isfile(path):
        return {}

    try:
        mtime = os.path.getmtime(path)
        if mtime == _cached_mtime:
            return _cached_creds

        env: dict[str, str] = {}
        with open(path) as fh:
            for line in fh:
                m = _EXPORT_RE.match(line)
                if m:
                    env[m.group(1)] = m.group(2)

        if "DB_USER" in env and "DB_PASSWORD" in env:
            _cached_mtime = mtime
            _cached_creds = env
            logger.info(
                "Loaded fresh Vault DB credentials (user=%s, mtime=%.0f)",
                env["DB_USER"][:12] + "…",
                mtime,
            )
            return env

    except OSError:
        logger.exception("Failed to read Vault secrets at %s", path)

    return _cached_creds or {}


class DatabaseWrapper(base.DatabaseWrapper):
    """
    Extends the stock PostgreSQL backend to inject live Vault credentials
    into every new connection's parameters.
    """

    def get_connection_params(self):
        params = super().get_connection_params()
        creds = _read_vault_creds()
        if creds:
            params["user"] = creds["DB_USER"]
            params["password"] = creds["DB_PASSWORD"]
        return params
